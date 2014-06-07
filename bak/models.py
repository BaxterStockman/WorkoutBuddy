from google.appengine.ext import ndb


class User(ndb.Model):
    username = ndb.StringProperty()
    password = ndb.StringProperty()
    email = ndb.StringProperty()


# Thanks to https://developers.google.com/appengine/docs/python/ndb/properties
# for ideas about nested models
class Address(ndb.Model):
    street = ndb.StringProperty()
    city = ndb.StringProperty()
    state = ndb.StringProperty()


class Contact(ndb.Model):
    fname = ndb.StringProperty()
    lname = ndb.StringProperty()
    address = ndb.StructuredProperty(Address)
    phone = ndb.StringProperty()
    email = ndb.StringProperty()
    updated = ndb.DateTimeProperty(auto_now=True)
    user_key = ndb.KeyProperty()
    blob_key = ndb.BlobKeyProperty()
    photo_url = ndb.TextProperty()
