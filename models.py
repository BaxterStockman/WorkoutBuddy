from google.appengine.ext import ndb


class Stats(ndb.Model):
    user_key = ndb.KeyProperty()
    date = ndb.DateTimeProperty(auto_now_add=True)
    weight = ndb.FloatProperty()
    height_inches = ndb.IntegerProperty()
    height_feet = ndb.IntegerProperty()
    body_fat = ndb.FloatProperty(validator=lambda prop, value: value >= 0 and
                                 value <= 100)
    height = None
    bmi = None


    def _assign_computed_stats(self):
        self.height = self._height_str()
        self.bmi = self._calc_bmi()

    def _height_str(self):
        if self.height_inches is None or self.height_feet is None:
            return None

        return "{}\'{}\"".format(self.height_feet, self.height_inches)

    def _calc_bmi(self):
        if self.height_inches is None or self.height_feet is None or self.weight is None:
            return None

        total_height = self.height_feet * 12 + self.height_inches
        bmi_raw = (self.weight / (total_height * total_height)) * 703
        return round(bmi_raw, 2)

    @classmethod
    def _post_get_hook(cls, key, future):
        obj = future.get_result()
        if obj is not None:
            obj._assign_computed_stats()

    def _pre_put_hook(self):
        self.weight = round(self.weight, 2)
        self.body_fat = round(self.body_fat, 2)

    def _post_put_hook(self, future):
        self._assign_computed_stats()


class User(ndb.Model):
    username = ndb.StringProperty(required=True)
    password = ndb.StringProperty(required=True)
    email = ndb.StringProperty(required=True)
    current_stats = ndb.StructuredProperty(Stats)
    starting_stats = ndb.StructuredProperty(Stats)
    report = ndb.TextProperty()

    def _assign_current_stats(self):
        if self.current_stats is not None:
            self.weight = self.current_stats.weight
            self.height = self.current_stats.height
            self.bmi = self.current_stats.bmi
            self.body_fat = self.current_stats.body_fat

    def _get_weight(self):
        if self.current_stats is None:
            return None
        return self.current_stats.weight

    def _height_str(self):
        if self.current_stats is None:
            return None
        return self.current_stats.height()

    def _calc_body_fat(self):
        if self.current_stats is None:
            return None
        return self.current_stats.body_fat

    def _calc_bmi(self):
        if self.current_stats is None:
            return None
        return self.current_stats.bmi()

    @classmethod
    def _post_get_hook(cls, key, future):
        obj = future.get_result()
        if obj is not None:
            obj._assign_current_stats()

    def _post_put_hook(self, future):
        self._assign_current_stats()


class Workout(ndb.Model):
    user_key = ndb.KeyProperty()
    name = ndb.StringProperty()
    updated = ndb.DateTimeProperty(auto_now=True)
    blob_key = ndb.BlobKeyProperty()
    photo_url = ndb.TextProperty()
    exercises = ndb.JsonProperty()
    text = ndb.TextProperty()
