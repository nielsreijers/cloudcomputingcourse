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
		"""Get all sensors for the application first, then get all samples per sensor.
		First attempt. It works, but causes multiple queries, which probably isn't efficient if we want all samples."""
		sensors = WKSensor.query(ancestor=WKApplication.key_for_application(application_name))

		# TODO: There must be a better way to do this? Can't I get all sensors and values in one query?
		for sensor in sensors:
			sensor.samples = WKSample.query(ancestor=sensor.key).fetch()
		return sensors

	def get_sensors2(self, application_name):
		"""Get everything for this application at once. Probably not a good idea if it's too much data, but
		if we do want everything, this should be more efficient than the previous query.
		The processing to change the flat list into a hierarchy of sensors and samples should be fast enough
		since it's just two simple passes over the list"""
		query = ndb.gql("SELECT * WHERE ANCESTOR IS :1 ORDER BY __key__", WKApplication.key_for_application(application_name))

		# Would this be sorted by __key__ as well? I'm not sure how to force that using this syntax.
		# query = ndb.Query(ancestor=WKApplication.key_for_application(application_name))

		# At this point we get a list containing the Application object first, followed by sensors
		# with all the samples for each sensor directly after that sensor object. (since it's sorted on __key__)
		# This means we don't need to search the list for the matching sensor, but can just use the last one we came across.
		current_sensor = None
		results = query.fetch()
		print results
		for result in results:
			if isinstance(result, WKSensor):
				current_sensor = result
				current_sensor.samples = []
			if isinstance(result, WKSample):
				current_sensor.samples.append(result)

		sensors = [result for result in results if isinstance(result, WKSensor)] # Just return the sensors, samples are now in a sublist
		return sensors

	def get(self):
		application_name = self.request.get('application')

		sensors = self.get_sensors2(application_name)

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

