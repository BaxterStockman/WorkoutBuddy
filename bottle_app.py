import beaker.middleware
import functools
import pprint
import re
import sys
import urllib
import urllib2
from forms import ContactForm, ContactSearchForm, LoginForm, SignupForm
from framework import bottle
from google.appengine.api.images import get_serving_url
from google.appengine.ext import ndb, blobstore
from google.appengine.ext.webapp import blobstore_handlers
from models import Address, Contact, User
from operator import itemgetter
from werkzeug.http import parse_options_header
from wtforms.ext.appengine.ndb import model_form
from wtforms import Form


'''
Thanks to user larsks for this handy way of dealing with
session variables.  Source:
http://stackoverflow.com/questions/13735333/bottle-py-session-with-beaker
'''

session_opts = {
    'session.type': 'ext:google',
    'session.cookie_expires': 10000,
    'session.auto': True,
}


# Set up middleware
app = beaker.middleware.SessionMiddleware(bottle.app(), session_opts)


'''
Kudos to Aaron Moodle at Reliably Broken for cluing
me in to the ability to curry* functions using
functools.partial.  Source:
http://reliablybroken.com/b/2010/08/curried-bottle-views/

* Well, not exactly.  It's like returning a NEW curried function whose
arguments happen to be the same as the initial function.

The following code sets a default value for keywords
across all calls to bottle.template()
'''
bottle.template = functools.partial(bottle.template,
    app_name="Positive Contact"
)


def defergetter(key):
    return itemgetter(key);


sort_keys = {
    'fname': defergetter('fname'),
    'lname': defergetter('lname'),
    'street': defergetter('street'),
    'city': defergetter('city'),
    'state': defergetter('state'),
    'email': defergetter('email'),
    'phone': defergetter('phone'),
}


@bottle.hook('before_request')
def setup_request():
    session = bottle.request.session = bottle.request.environ.get('beaker.session')
    bottle.BaseTemplate.defaults['session'] = session
    bottle.BaseTemplate.defaults['path'] = bottle.request.path


@bottle.get('/')
def index(key_query=None, filter_query=None, filter_form=None):
    # If we don't have a get query or saved sort key, default to sorting by lname
    if key_query is None:
        if bottle.request.query.key_query:
            key_query = bottle.request.query.key_query
        elif 'key_query' in bottle.request.session:
            key_query = bottle.request.session['key_query']
        else:
            key_query = 'lname'

    # Save key_query so that we get consistent results across refreshes
    bottle.request.session['key_query'] = key_query

    # Grab a sort function to pass to sorted()
    sort_key = sort_keys[key_query]

    if filter_form is None:
        filter_form = ContactForm()
        filter_func = lambda x: True
    else:
        filter_func = functools.partial(contact_filter, filter_form.data)

    # Refresh contacts and filter by any user-entered conditions
    contacts = refresh_contact_dict()
    filtered_contacts = filter(filter_func, contacts)

    # Grab contacts and place in dictionary for sorting
    if contacts:
        sorted_contacts = sorted(filtered_contacts, key=sort_key)
        return bottle.template('templates/base',
                               search_form=ContactSearchForm(),
                               filter_form=filter_form, contacts=sorted_contacts)

    else:
        return bottle.template('templates/base')


@bottle.post('/')
def index_filter():
    filter_data = bottle.request.forms

    if filter_data is None:
        filter_form = ContactForm()

    else:
        filter_form = ContactForm(filter_data.decode())

    return index(filter_form=filter_form)


@bottle.get('/login')
def login_form(form=None):
    # If the user is logged in, log out before rendering the log in form
    if 'user_key_str' in bottle.request.session:
        return logout_submit('/login')

    # Create a new form
    if form == None:
        form = LoginForm()

    return bottle.template('templates/base', {
        'target': "Login",
        'action': "/login",
        'form': form
    })


@bottle.post('/login')
def login_submit(form=None):
    if form is None:
        form = LoginForm(bottle.request.forms.decode())

    if form.validate():
        user = User.query(User.username == form.username.data).get()

        # Check that username and password are valid; otherwise raise error
        # messages and re-render form
        if user is None:
            form.username.errors.append('Unknown username')
            return login_form(form)
        elif form.password.data != user.password:
            form.password.errors.append('Invalid password')
            return login_form(form)

        user_key_str = user.key.urlsafe()
        session_add('user_key_str', user_key_str)
        session_add('username', form.username.data)

        bottle.redirect('/')
    else:
        return login_form(form)


@bottle.route('/logout')
def logout_submit(dest='/'):
    bottle.request.session.delete()
    bottle.redirect(dest)


@bottle.get('/signup')
def signup_form(form=None):
    if form == None:
        form = SignupForm()

    return bottle.template('templates/base', {
        'target': "Sign up",
        'form': form,
        'action': 'signup',
    })


@bottle.post('/signup')
def signup_submit():
    form = SignupForm(bottle.request.forms.decode())
    if form.validate():
        try:
            user = User(
                username=form.username.data,
                password=form.password.data,
                email=form.email.data,
            )
        except:
            print("Failed to create new user: {0}".format(sys.exc_info()[0]))

        # Add new user to database
        user.put()

        user_key_str = user.key.urlsafe()
        session_add('user_key_str', user_key_str)
        session_add('username', form.username.data)

        bottle.redirect('/')
    else:
        return signup_form(form)


'''
ENDLESS THANKS to user Koffee at
http://stackoverflow.com/questions/18061264/serve-image-from-gae-datastore-with-flask-python
for hints on how to integrate the Blobstore with Python web
frameworks other than webapp2
'''
@bottle.get('/add')
def add_form(form=None, upload_url=None):
    if form == None:
        form = ContactForm()

    if upload_url == None:
        upload_url = blobstore.create_upload_url("/add")

    return bottle.template('templates/base', {
        'target': "Add",
        'form': form,
        'action': upload_url,
    })


@bottle.post('/add')
def add_submit():
    form_data = bottle.request.forms

    '''
    Bottle keeps file data in a bottle.request.files and
    doesn't maintain any file info in bottle.request.forms,
    so we've got to manually append relevant info.  Here, we
    send the file's mimetype so that WTForms can check whether
    it is an image file.

    Later, we send the image file itself to the GAE blobstore.
    '''

    form = ContactForm(form_data.decode())

    if form.validate():
        # Check that a photo was uploaded
        if 'photo' in bottle.request.files:
            photo = bottle.request.files['photo']
            parsed_ct = parse_options_header(photo.content_type)
            blob_key = parsed_ct[1]['blob-key']
            photo_url = get_serving_url(blob_key, size=32, crop=True)
        else:
            # Set to None so that we don't get any funny business
            # on the call to create_contact
            photo_url = None
            blob_key = None

        # Retrieve the user's Datastore key string and create a contact linked
        # to that key
        user_key_str = bottle.request.session['user_key_str']
        key = create_contact(form, user_key=ndb.Key(urlsafe=user_key_str),
                             photo_url=photo_url, blob_key=blob_key)

        if 'contacts' in bottle.request.session:
            bottle.request.session['contacts'].append(contact_to_dict(key.get()))

        return refresh_path('/')

    else:
        return add_form(form=form,
                        upload_url=blobstore.create_upload_url("/add"))


@bottle.get('/edit/<key_str>')
def get_contact(key_str, form=None, upload_url=None):
    if form == None:
        # Retrieve contact data and create a form
        contact = ndb.Key(urlsafe=key_str).get()
        #bottle.request.session['contact'] = contact
        form = contact_to_form(contact)
    if upload_url == None:
        upload_url = blobstore.create_upload_url("/edit/" + key_str)

    return bottle.template('templates/base', {
        'target': "Edit",
        'form': form,
        'action': upload_url,
    })


@bottle.post('/edit/<key_str>')
def edit_contact(key_str):
    form_data = bottle.request.forms
    form = ContactForm(form_data.decode())

    if form.validate():
        # Check that a photo was uploaded
        if 'photo' in bottle.request.files:
            photo = bottle.request.files['photo']
            parsed_ct = parse_options_header(photo.content_type)
            blob_key = parsed_ct[1]['blob-key']
            photo_url = get_serving_url(blob_key, size=32, crop=True)
        else:
            # Set to None so that we don't get any funny business
            # on the call to create_contact
            photo_url = None
            blob_key = None

        # Retrieve contact's Datastore key
        key = ndb.Key(urlsafe=key_str)

        # Delete the record
        key.delete()

        # Retrieve the user's Datastore key string and create a contact linked
        # to that key
        user_key_str = bottle.request.session['user_key_str']
        key = create_contact(form, user_key=ndb.Key(urlsafe=user_key_str),
                             photo_url=photo_url, blob_key=blob_key)

        return refresh_path('/')

    else:
        return get_contact(key_str, form=form, upload_url=blobstore.create_upload_url("/edit/" + key_str))


@bottle.route('/delete/<key_str>')
def delete_contact(key_str):
    key = ndb.Key(urlsafe=key_str)
    key.delete()

    contacts = bottle.request.session['contacts']

    #del_contact = lambda c: c['key_str'] != key_str
    get_contact = lambda c: c['key_str'] == key_str
    contact = filter(get_contact, contacts)

    if 'photo_url' in contact:
        delete_serving_url(contact['photo_url'])

    # filter out the deleted contact from session contact dictionary
    #bottle.request.session['contacts'] = filter(not get_contact, contacts)
    #return change_path(index, '/', contacts=contacts)
    #refresh_path('/')
    bottle.redirect('/')


@bottle.error(403)
def error403(code):
    return "Invalid code specified"


@bottle.error(404)
def error404(code):
    return bottle.template('templates/404')


'''
Helper functions
'''
def refresh_contact_dict():
    if 'user_key_str' in bottle.request.session:
        user_key = ndb.Key(urlsafe=bottle.request.session['user_key_str'])
        if user_key:
            contacts = map(contact_to_dict, Contact.query(Contact.user_key == user_key).fetch())
            bottle.request.session['contacts'] = contacts
            return contacts
    return {}


def contact_to_dict(contact):
    address = contact.address
    return {
        'fname': contact.fname,
        'lname': contact.lname,
        'street': address.street,
        'city': address.city,
        'state': address.state,
        'phone': contact.phone,
        'email': contact.email,
        'key_str': contact.key.urlsafe(),
        'blob_key': contact.blob_key,
        'photo_url': contact.photo_url,
    }


def contact_to_form(contact):
    address = contact.address
    return ContactForm(
        fname=contact.fname,
        lname=contact.lname,
        street=address.street,
        city=address.city,
        state=address.state,
        phone=contact.phone,
        email=contact.email,
    )


def print_form_data(form):
    for field in form:
        print(field.label)
        print(field.data)


def create_contact(form, user_key=None, photo_url=None, blob_key=None):
    try:
        new_address = Address(
            street=form.street.data,
            city=form.city.data,
            state=form.state.data,
        )
    except:
        print("Failed to create new address: {0}".format(sys.exc_info()[0]))

    try:
        new_contact = Contact(
            fname=form.fname.data,
            lname=form.lname.data,
            address=new_address,
            email=form.email.data,
            phone=form.phone.data,
            user_key=user_key,
            photo_url=photo_url,
        )
    except:
        print("Failed to create new contact: {0}".format(sys.exc_info()[0]))

    return new_contact.put()


def refresh_path(path, timeout=0):
    return '<meta http-equiv="REFRESH" content="{0};url={1}">'.format(timeout, path)


def session_add(key, value):
    bottle.request.environ.get('beaker.session')[key] = value


def change_path(cb, path='/', *args, **kwargs):
    bottle.request.path = path
    return cb(*args, **kwargs)


def contact_filter(filter_dict, contact):
    if filter_dict is None:
        return True

    # Iterate over key-value pairs in filter dictionary, checking whether (1)
    # the key occurs in the contact dictionary and (2), if so, whether the
    # filter dictionary value occurs as a substring of the contact dictionary
    # value
    for key, value in filter_dict.iteritems():
        if value is None or value == "":
            continue
        if key not in contact:
            return False
        else:
            if contact[key].lower().find(value.lower()) < 0:
                return False

    return True


'''
Run test server
'''
if __name__ == "__main__":
    bottle.run(server="gae", app=app, debug=True)
