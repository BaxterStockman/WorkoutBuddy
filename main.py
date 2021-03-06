#import gevent.monkey; gevent.monkey.patch_all()
import flask
import os
import simplejson as json
import sys

from beaker.middleware import SessionMiddleware
from flask import (
    Flask,
    flash,
    session,
    request,
    url_for,
    redirect,
    render_template,
    Response,
)
from flask.ext.bootstrap import Bootstrap, WebCDN
from flask.sessions import SessionInterface
from forms import LoginForm, SignupForm, StatsForm, WorkoutForm
from google.appengine.api.images import get_serving_url
from google.appengine.ext import ndb, blobstore
from google.appengine.ext.webapp import blobstore_handlers
from models import User, Workout, Stats
from operator import itemgetter
from werkzeug.http import parse_options_header
from wtforms import SelectField
from wtforms.validators import InputRequired


class BeakerSessionInterface(SessionInterface):
    def open_session(self, app, request):
        session = request.environ['beaker.session']
        return session

    def save_session(self, app, session, response):
        session.save()


def create_app():
    app = Flask(__name__)
    app.config.update(
        SECRET_KEY='secret',
    )

    cdns = {
        "jquery": WebCDN("//ajax.googleapis.com/ajax/libs/jquery/1.11.0/"),
        "jquery-ui": WebCDN("//ajax.googleapis.com/ajax/libs/jqueryui/1.10.4/"),
    }

    Bootstrap(app)
    app.extensions['bootstrap']['cdns'].update(cdns)

    session_opts = {
        'session.type': 'ext:google',
        'session.cookie_expires': 10000,
        'session.auto': True,
    }

    app.wsgi_app = SessionMiddleware(app.wsgi_app, session_opts)
    app.session_interface = BeakerSessionInterface()

    return app


app = create_app()


# Hooks
@app.teardown_appcontext
def shutdown_db_session(exception=None):
    pass
    #db_session.remove()


@app.route('/')
def index():
    username = session.get('username')
    user_key_str = session.get('user_key_str')
    workouts = None
    report = None

    if user_key_str is not None:
        workouts = refresh_workout_dict(user_key_str)
        user = get_current_user()
        report = user.report

    return flask.render_template('index.html', workouts=workouts, report=report)


@app.route('/login', methods=["GET", "POST"])
def login():
    form = LoginForm()
    template = 'basic_form.html'
    header = "Log in"

    if form.validate_on_submit():
        user = User.query(User.username == form.username.data).get()
        if user is None:
            form.username.errors.append('Unknown username')
            return flask.render_template(template, header=header, form=form)
        elif form.password.data != user.password:
            form.password.errors.append('Invalid password')
            return flask.render_template(template, header=header, form=form)

        user_key_str = user.key.urlsafe()
        session['user_key_str'] = user_key_str
        session['username'] = form.username.data
        flash("Successfully logged in.")
        return flask.redirect(flask.url_for('index'))

    return flask.render_template(template, header=header, form=form)


@app.route('/logout')
def logout():
    flash("Successfully logged out.")
    session.delete()
    return redirect(url_for('index'))


@app.route('/signup', methods=["GET", "POST"])
def signup():
    form = SignupForm()
    if form.validate_on_submit():
        username = form.username.data
        email = form.email.data

        if User.query(User.username == username).get() is not None:
            form.username.errors.append('That username already exists')
            return flask.render_template('signup.html', form=form)

        if User.query(User.email == email).get() is not None:
            form.email.errors.append('That email address is already registered')
            return flask.render_template('signup.html', form=form)

        user = create_user(form)

        if user is None:
            flask.flash("Failed to create account; please try again.", 'warning')
            return flask.render_template('signup.html', form=form)

        # Add user info to session
        user_key_str = user.key.urlsafe()
        session['username'] = username
        session['user_key_str'] = user.key.urlsafe()

        flask.flash("Successfully created account, {0}!".format(username))
        return flask.redirect(flask.url_for('index'))
    return flask.render_template('basic_form.html', header='Sign up', form=form)


@app.route('/workout', methods=["GET", "POST"])
def add_workout():
    form = WorkoutForm()
    upload_url = blobstore.create_upload_url(url_for('add_workout'))

    if form.validate_on_submit():
        photo_url, blob_key = get_photo_url_and_blob_key()

        user_key_str = session.get('user_key_str')
        if user_key_str is None:
            flask.flash("You are not current logged in.", 'warning')
            return flask.redirect(flask.url_for('index'))

        workout = create_workout(form, user_key=ndb.Key(urlsafe=user_key_str),
                             photo_url=photo_url, blob_key=blob_key)

        # Add new workout to list stored in session
        workout_dict = workout_to_dict(workout)
        if 'workouts' not in session:
            session['workouts'] = []
        session['workouts'].append(workout_dict)

        flash("Successfully added new workout.")
        return redirect(flask.url_for('index'))
    return render_template('workout.html', header='Add a workout', form=form, action=upload_url)


@app.route('/stats', methods=["GET", "POST"])
def add_stats():
    # remember: url_for('add', username=session.get('username'))
    form = StatsForm()
    if form.validate_on_submit():
        # Create new stats object
        user_key_str = session.get('user_key_str')

        if user_key_str is None:
            flask.flash("You are not current logged in.", 'warning')
            return flask.redirect(flask.url_for('index'))

        stats = create_stats(form, user_key=ndb.Key(urlsafe=user_key_str))
        stats_dict = stats_to_dict(stats)
        session['stats'] = stats_dict

        user = get_current_user()

        if user is None:
            flask.flash("You are not current logged in.", 'warning')
            return flask.redirect(flask.url_for('index'))

        if user.starting_stats is None:
            user.starting_stats = stats
        user.current_stats = stats
        user.put()


        flask.flash("Successfully updated your stats.")
        return flask.redirect(flask.url_for('index'))
    return flask.render_template('basic_form.html', header='Update your stats', form=form)


@app.route('/upload', methods=["POST"])
def upload():
    failed = False

    # Need 'force=True' for file upload
    data = request.get_json(force=True)

    # So very, very insecure
    username = data.get('username')
    password = data.get('password')

    user = query_user(username, password)

    if user is None:
        return redirect(url_for('page_unauthorized'), 'No such user')

    action = data.get('action')

    user_key = user.key

    if action == 'workout':
        photo_url, blob_key = get_photo_url_and_blob_key()
        try:
            workout_dict = data.get('workout')
            new_workout = Workout(
                user_key = user_key,
                name = workout_dict.get('name'),
                blob_key = blob_key,
                photo_url = photo_url,
                text = workout_dict.get('text'),
                exercises = workout_dict.get('exercises')
            )
            new_workout.put()
        except:
            print("Failed to create new workout: {0}".format(sys.exc_info()[0]))
            failed = True
    elif action == 'stats':
        try:
            stats_dict = data.get('stats')
            new_stats = Stats(
                user_key = user_key,
                weight = stats_dict.get('weight'),
                height_inches = stats_dict.get('height_inches'),
                height_feet = stats_dict.get('height_feet'),
                body_fat = stats_dict.get('body_fat'),
            )
            new_stats.put()
        except:
            print("Failed to create new workout: {0}".format(sys.exc_info()[0]))
            failed = True
    else:
        return redirect(url_for('page_unauthorized'), 'No such operation')


    if failed:
        return "failed"
    return "success"




@app.route('/analyze')
def analyze():
    """
        - Get list of all users
        - For each user, pull starting {weight,bmi,fat} and current {same}
        - Update 'delta' for each
    """
    count = 0
    user_query = User.query()
    for user in user_query.iter():
        current_stats = user.current_stats
        starting_stats = user.starting_stats

        # Don't bother doing a report if there's nothing to report
        if current_stats is None or starting_stats is None:
            break

        current_bmi = current_stats._calc_bmi()
        starting_bmi = starting_stats._calc_bmi()

        if(current_stats.weight <= starting_stats.weight):
            weight_report = "You have lost {0} pounds.".format(starting_stats.weight - current_stats.weight)
        else:
            weight_report = "You have gained {0} pounds.".format(current_stats.weight - starting_stats.weight)

        if(current_bmi <= starting_bmi):
            bmi_report = "Your body mass has decreased by {0}.".format(starting_bmi - current_bmi)
        else:
            bmi_report = "Your body mass has increased by {0}.".format(current_bmi - starting_bmi)

        if(current_stats.body_fat <= starting_stats.body_fat):
            body_fat_report = "You have lost {0} percent body fat.".format(starting_stats.body_fat - current_stats.body_fat)
        else:
            body_fat_report = "You have gained {0} percent body fat.".format(current_stats.body_fat - starting_stats.body_fat)

        report = '  '.join([weight_report, bmi_report, body_fat_report])

        user.report = report
        user.put()
    return redirect(url_for('index'))


# Delete the session if something's gone horribly wrong
@app.route('/nuke')
def nuke():
    session.invalidate()


@app.route('/test', methods=["GET", "POST"])
def test():
    session['test'] = "THIS IS A TEST"
    ret = session.get('fakekey')
    if ret is None:
        return "Sorry!"
    return ret


@app.errorhandler(401)
def page_unauthorized(e):
    return Response(e, 401, {'WWWAuthenticate':'Basic realm="Login Required"'})

@app.errorhandler(404)
def page_not_found(e):
    return flask.render_template('404.html'), 404


@app.errorhandler(500)
def internal_server_error(e):
    return flask.render_template('500.html'), 500


def get_photo_url_and_blob_key():
    photo_url = None
    blob_key = None

    if 'photo' in request.files:
        photo = request.files['photo']
        parsed_ct = parse_options_header(photo.content_type)
        try:
            blob_key = parsed_ct[1]['blob-key']
            photo_url = get_serving_url(blob_key)
        except:
            print("Failed to obtain photo url: {0}".format(sys.exc_info()[0]))

    return photo_url, blob_key


def create_workout(form, user_key=None, photo_url=None, blob_key=None):
    try:
        new_workout = Workout(
            user_key = user_key,
            name = form.name.data,
            blob_key = blob_key,
            photo_url = photo_url,
            exercises = form.workout_set.data
        )
        new_workout.put()
    except:
        print("Failed to create new workout: {0}".format(sys.exc_info()[0]))
        return None

    return new_workout


def workout_to_dict(workout):
    if workout is None:
        return None

    return {
        'name': workout.name,
        'blob_key': workout.blob_key,
        'photo_url': workout.photo_url,
        'exercises': workout.exercises,
        'text': workout.text,
    }


def create_stats(form, user_key=None):
    try:
        new_stats = Stats(
            user_key = user_key,
            weight = form.weight.data,
            height_inches = form.height_inches.data,
            height_feet = form.height_feet.data,
            body_fat = form.body_fat.data,
        )
        new_stats.put()
    except:
        print("Failed to update user stats: {0}".format(sys.exc_info()[0]))
        return None

    return new_stats


def stats_to_dict(stats):
    if stats is None:
        return None

    return {
        'weight': stats.weight,
        'height_inches': stats.height_inches,
        'height_feet': stats.height_feet,
        'height': stats._height_str(),
        'body_fat': stats.body_fat,
        'bmi': stats._calc_bmi(),
    }


def create_user(form, current_stats=None, starting_stats=None):
    try:
        user = User(
            username=form.username.data,
            password=form.password.data,
            email=form.email.data,
            current_stats=current_stats,
            starting_stats=starting_stats,
        )
        user.put()
    except:
        print("Failed to create new user: {0}".format(sys.exc_info()[0]))
        return None

    return user


def user_to_dict(user, current_stats=None, starting_stats=None):
    if isinstance(current_stats, Stats):
        current_stats = stats_to_dict(current_stats)
    else:
        current_stats = user.current_stats

    if isinstance(starting_stats, Stats):
        starting_stats = stats_to_dict(starting_stats)
    else:
        starting_stats = user.starting_stats

    return {
        'username': user.username,
        'weight': user.weight,
        'height': user.height,
        'body_fat': user.body_fat,
        'bmi': user.bmi,
        'current_stats': stats_to_dict(current_stats),
        'starting_stats': stats_to_dict(starting_stats),
    }


def refresh_workout_dict(user_key_str, new_workout=None):
    user_key = ndb.Key(urlsafe=user_key_str)
    if user_key:
        workouts = map(workout_to_dict, Workout.query(Workout.user_key == user_key).fetch())
    else:
        workouts = []

    if new_workout is not None:
        workouts.append(workout_to_dict(new_workout))

    session['workouts'] = workouts
    return workouts

def refresh_stats_dict(user_key_str):
    user_key = ndb.Key(urlsafe=user_key_str)
    if user_key:
        #user = User.query(User._key == user_key).fetch())
        stats = {}
    else:
        stats = {}

    session['stats'] = stats
    return workouts

def print_form_data(form, print_type=False):
    for field in form:
        if print_type is True:
            print("({0}): {1}".format(field.label, type(field.data),
                                          field.data))
        else:
            print("{0}".format(field.data))

def get_current_user(user_key_str=None):
    user_key_str = user_key_str or session.get('user_key_str')
    if user_key_str is None:
        return None

    # Get the user by converting the urlsafe key to ndb key, then pulling id
    try:
        user_id = ndb.Key(urlsafe=user_key_str).id()
        return User.get_by_id(user_id)
    except:
        print("Failed to source user: {0}".format(sys.exc_info()[0]))
        return None

def query_user(username, password):
    return User.query(User.username == username).filter(User.password == password).get()
