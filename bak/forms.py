from cgi import escape
from models import User, Address, Contact
from wtforms import Form, BooleanField, FileField, SelectField, StringField, PasswordField
from wtforms.compat import text_type
from wtforms.ext.appengine.ndb import model_form
from wtforms.validators import InputRequired, Email, EqualTo, Optional, Regexp, ValidationError
from wtforms.widgets import html_params, HTMLString
import functools

state_list = ['State',
              'AL', 'AK', 'AZ', 'AR', 'CA', 'CO', 'CT', 'DE', 'FL', 'GA', 'HI',
              'IA', 'ID', 'IL', 'IN', 'KS', 'KY', 'LA', 'MA', 'MD', 'ME', 'MI',
              'MN', 'MO', 'MS', 'MT', 'NC', 'ND', 'NE', 'NH', 'NJ', 'NM', 'NV',
              'NY', 'OH', 'OK', 'OR', 'PA', 'RI', 'SC', 'SD', 'TN', 'TX', 'UT',
              'VA', 'VT', 'WA', 'WI', 'WV', 'WY']
state_select = [(state, state) for state in state_list]
state_select[0] = ("", 'State')


class SelectWithDisable(object):
    def __init__(self, multiple=False):
        self.multiple = multiple

    def __call__(self, field, **kwargs):
        kwargs.setdefault('id', field.id)
        if self.multiple:
            kwargs['multiple'] = True
        html = ['<select %s>' % html_params(name=field.name, **kwargs)]
        for val, label, selected, disabled in field.iter_choices():
            html.append(self.render_option(val, label, selected, disabled))
        html.append('</select>')
        return HTMLString(''.join(html))

    @classmethod
    def render_option(cls, value, label, selected, disabled=False, **kwargs):
        options = dict(kwargs, value=value)
        if selected:
            options['selected'] = True
        if disabled:
            options['disabled'] = True
        return HTMLString('<option %s>%s</option>' % (html_params(**options), escape(text_type(label))))


class SelectFieldWithDisable(SelectField):
    widget = SelectWithDisable()

    def __init__(self, label=None, validators=None, coerce=text_type,
                 choices=None, disabled=[], **kwargs):
        super(SelectFieldWithDisable, self).__init__(label, validators, coerce, choices, **kwargs)
        self.disabled = dict((opt, True) for opt in disabled)

    def iter_choices(self):
        for value, label in self.choices:
            # This line is odd.  According to the docs, the values for a select
            # field are tuples of the form (value, label).  However, in order
            # to get an empty string for the value of 'State' (my default
            # option), while also disabling it, I have to do 'value in
            # self.disabled' instead of 'label in self.disabled', and pass the
            # tuple '("", 'State')'.  Strange.
            yield (value, label, self.coerce(value) == self.data, value in self.disabled)


class ContactForm(Form):
    fname = StringField('First name', [InputRequired(message="You must provide a first name")])
    lname = StringField('Last name', [InputRequired(message="You must provide a last name")])
    email = StringField('Email', [Email(message="That's not a valid email address"), Optional()])
    phone = StringField('Phone number', [Regexp('\d{3}\D*\d{3}\D*\d{4}\D*\d*',
                                                message="That's not a valid phone number"),
                                         Optional()])
    street = StringField('Street Address', [Regexp('\d+\s+[\w\s.\d]+'),
                                            Optional()])
    city = StringField('City')
    state = SelectFieldWithDisable('State', choices=state_select,
                                   disabled=['State'], default='State')
    photo = FileField('Photo', [Regexp('\Aimage/', message="That's not an image file"), Optional()])


class ContactSearchForm(Form):
    query = StringField('Search')
    state = SelectFieldWithDisable('Filter by State', choices=state_select,
                                   disabled=['State'], default='State')


class LoginForm(Form):
    username = StringField('Username', [InputRequired(message="Please provide your username")])
    password = PasswordField('Password', [InputRequired(message="Please provide your password")])


class SignupForm(Form):
    email = StringField('Email', [Email(message="That's not a valid email address"),
                                  InputRequired()])
    username = StringField('Username', [InputRequired(message="Please provide a username")])
    password = PasswordField(
        'Password',
        [InputRequired("Please provide a password"),
         EqualTo('password', message="Passwords must match")])
    check_password = PasswordField('Re-enter password')
