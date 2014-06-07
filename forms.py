from cgi import escape
from flask.ext.wtf import Form
from wtforms import (
    HiddenField,
    PasswordField,
    RadioField,
    SelectField,
    SelectMultipleField,
    StringField,
    SubmitField,
    TextAreaField,
)
from wtforms.compat import text_type
from wtforms.ext.dateutil.fields import DateTimeField
from wtforms.validators import (
    InputRequired,
    Email,
    EqualTo,
    ValidationError,
)
from wtforms.widgets import html_params, HiddenInput, HTMLString


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


class DateTimePickerField(DateTimeField):
    def __call__(self, **kwargs):
        return super(DateTimePickerField, self).__call__(class_="datetimepicker", **kwargs)


class LoginForm(Form):
    username = StringField('Username', [InputRequired(message="Please provide your username")])
    password = PasswordField('Password', [InputRequired(message="Please provide your password")])
    submit = SubmitField('Login')


class SignupForm(Form):
    email = StringField('Email', [Email(message="That's not a valid email address"),
                                  InputRequired()])
    username = StringField('Username', [InputRequired(message="Please provide a username")])
    password = PasswordField(
        'Password',
        [InputRequired("Please provide a password"),
         EqualTo('check_password', message="Passwords must match")])
    check_password = PasswordField('Re-enter password')
    submit = SubmitField('Sign up')


# Adapted from http://wtforms.readthedocs.org/en/latest/widgets.html
def select_multi_checkbox(field, ul_class='', ul_role='', **kwargs):
    kwargs.setdefault('type', 'checkbox')
    field_id = kwargs.pop('id', field.id)
    html = [u'<ul %s>' % html_params(id=field_id, class_=ul_class, role=ul_role)]
    for value, label, checked in field.iter_choices():
        choice_id = u'%s-%s' % (field_id, value)
        options = dict(kwargs, name=field.name, value=value, id=choice_id)
        if checked:
            options['checked'] = 'checked'
        html.append(u'<li><input %s /> ' % html_params(**options))
        html.append(u'<label for="%s">%s</label></li>' % (field_id, label))
    html.append(u'</ul>')
    return u''.join(html)

class HiddenListField(HiddenField):
    widget = HiddenInput()

    def __init__(self, label='', validators=None, remove_duplicates=True, **kwargs):
        super(HiddenListField, self).__init__(label, validators, **kwargs)
        self.remove_duplicates = remove_duplicates

    def _value(self):
        if self.data:
            return u','.join(self.data)
        else:
            return u''

    def process_formdata(self, valuelist):
        self.data = valuelist
        if self.remove_duplicates:
            self.data = [x.strip() for x in valuelist[0].split(',')]
        else:
            self.data = []

    @classmethod
    def _remove_duplicates(cls, seq):
        d = {}
        for item in seq:
            lc_item = item.lower()
            if lc_item not in d:
                d[lc_item] = True
                yield item
