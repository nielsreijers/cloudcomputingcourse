import cgi
import datetime
import urllib
import webapp2
import os
import jinja2

from google.appengine.api import users
from google.appengine.ext import ndb


JINJA_ENVIRONMENT = jinja2.Environment(
    loader=jinja2.FileSystemLoader(os.path.dirname(__file__)),
    extensions=['jinja2.ext.autoescape'])


# Let's see if I can delay creating the application objects and just the key as ancestors for WKSensor
# class WKApplication(ndb.Model):
# 	"""Root object which models an wukong application"""
# 	name = ndb.StringProperty()

class WKSensor(ndb.Model):
	"""Models a sensor in an wukong application"""
	name = ndb.StringProperty()

	@staticmethod
	def wksensor_parent_key(application_name):
		return ndb.Key('WKApplication', application_name)

class WKSample(ndb.Model):
	"""Models a single measurement in a wukong application"""
	value = ndb.IntegerProperty()
	time = ndb.DateTimeProperty(auto_now_add=True)

class SensorLog(webapp2.RequestHandler):
	def get(self):
		application_name = self.request.get('application')
		sensors = WKSensor.query(ancestor=WKSensor.wksensor_parent_key(application_name))

		# TODO: There must be a better way to do this? Can't I get all sensors and values in one query?
		for sensor in sensors:
			sensor.samples = WKSample.query(ancestor=sensor.key).fetch()

		template_values = {'sensors': sensors,
						'application': application_name}
		template = JINJA_ENVIRONMENT.get_template('sensor_log.html')
		self.response.write(template.render(template_values))

class LogSample(webapp2.RequestHandler):
	def post(self):
		return self.get()

	def get(self):
		"""Logs a sample to the data store under the specified application and sensor name
		Application and sensor will be created if they don't exist yet."""
		application_name = self.request.get('application')
		sensor_name = self.request.get('sensor')
		value = self.request.get('value')

		sensor = WKSensor.get_or_insert(sensor_name,
										parent=WKSensor.wksensor_parent_key(application_name),
										name=sensor_name)

		sample = WKSample(parent=sensor.key,
						value = int(value))
		sample.put()

		query_params = {'application': application_name}
		self.redirect('/sensorlog?' + urllib.urlencode(query_params))


app = webapp2.WSGIApplication([('/sensorlog', SensorLog),
								('/logsample', LogSample)],
                              debug=True)

