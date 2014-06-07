#import gevent.monkey; gevent.monkey.patch_all()
import flask
import os
import pprint
import werkzeug.serving

from flask.ext.bootstrap import Bootstrap, WebCDN
from forms import LoginForm, SignupForm
from wtforms import SelectField
from wtforms.validators import InputRequired


def create_app():
    app = flask.Flask(__name__)
    app.config.update(
        SECRET_KEY='secret',
    )

    cdns = {
        "jquery": WebCDN("//ajax.googleapis.com/ajax/libs/jquery/1.11.0/"),
        "jquery-ui": WebCDN("//ajax.googleapis.com/ajax/libs/jqueryui/1.10.4/"),
        "socket.io": WebCDN("//cdnjs.cloudflare.com/ajax/libs/socket.io/0.9.16/"),
        "typeahead": WebCDN("//cdnjs.cloudflare.com/ajax/libs/typeahead.js/0.10.2/"),
        "handlebars": WebCDN("//cdnjs.cloudflare.com/ajax/libs/handlebars.js/2.0.0-alpha.2/"),
    }

    Bootstrap(app)
    app.extensions['bootstrap']['cdns'].update(cdns)

    return app


app = create_app()


# Hooks
@app.teardown_appcontext
def shutdown_db_session(exception=None):
    pass
    #db_session.remove()


@app.route('/')
def index():
    return flask.render_template('index.html')


@app.route('/login', methods=["GET", "POST"])
def login_form():
    form = LoginForm()
    if form.validate_on_submit():
        flask.flash("Success!")
        flask.session['username'] = form.username.data
        return flask.redirect(flask.url_for('index'))
    return flask.render_template('login.html', form=form)


@app.route('/signup', methods=["GET", "POST"])
def signup_form():
    form = SignupForm()
    if form.validate_on_submit():
        flask.flash("Success!")
        flask.session['username'] = form.username.data
        return flask.redirect(flask.url_for('index'))
    return flask.render_template('signup.html', form=form)


@app.route('/add', methods=["GET", "POST"])
def event_form():
    form = EventForm()
    if form.validate_on_submit():
        flask.flash("Success!")
        print(form.start.data)
        print(form.end.data)
        return flask.redirect(flask.url_for('index'))
    return flask.render_template('search.html', form=form)


@app.errorhandler(404)
def page_not_found(e):
    return flask.render_template('404.html'), 404


@app.errorhandler(500)
def internal_server_error(e):
    return flask.render_template('500.html'), 500
