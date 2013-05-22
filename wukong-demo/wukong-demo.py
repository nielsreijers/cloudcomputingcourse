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


class WKApplication(ndb.Model):
	"""Root object which models an wukong application"""
	name = ndb.StringProperty()

	@staticmethod
	def key_for_application(application_name):
		return ndb.Key('WKApplication', application_name)

class WKSensor(ndb.Model):
	"""Models a sensor in an wukong application"""
	name = ndb.StringProperty()

class WKSample(ndb.Model):
	"""Models a single measurement in a wukong application"""
	value = ndb.IntegerProperty()
	time = ndb.DateTimeProperty(auto_now_add=True)

class SensorLog(webapp2.RequestHandler):
	def get_sensors1(self, application_name):
		sensors = WKSensor.query(ancestor=WKApplication.key_for_application(application_name))

		# TODO: There must be a better way to do this? Can't I get all sensors and values in one query?
		for sensor in sensors:
			sensor.samples = WKSample.query(ancestor=sensor.key).fetch()
		return sensors

	def get(self):
		application_name = self.request.get('application')

		sensors = self.get_sensors1(application_name)

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

		application = WKApplication.get_or_insert(application_name,
													name=application_name)

		sensor = WKSensor.get_or_insert(sensor_name,
										parent=application.key,
										name=sensor_name)

		sample = WKSample(parent=sensor.key,
						value = int(value))
		sample.put()

		query_params = {'application': application_name}
		self.redirect('/sensorlog?' + urllib.urlencode(query_params))


app = webapp2.WSGIApplication([('/sensorlog', SensorLog),
								('/logsample', LogSample)],
                              debug=True)

