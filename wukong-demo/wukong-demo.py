import cgi
import datetime
import urllib
import webapp2
import os
import jinja2
import operator

from google.appengine.api import users
from google.appengine.ext import ndb


JINJA_ENVIRONMENT = jinja2.Environment(
    loader=jinja2.FileSystemLoader(os.path.dirname(__file__)),
    extensions=['jinja2.ext.autoescape'])


# Data model requirements:
# One application will have several sensors.
# Sensors log values at set intervals. Maximum frequency: 1 sample/second
# Applications will run for months.
# -> Several samples per second per application
# -> Possibly millions of samples per sensor

# Since there's a limit of 1 write/second per entity group,
# this suggests sensors+their samples can be a group, but the
# link from sensor to application should be a reference instead

class WKApplication(ndb.Model):
	"""Root object which models an wukong application"""
	name = ndb.StringProperty()

	@staticmethod
	def key_for_application(application_name):
		return ndb.Key(WKApplication, application_name)

class WKSensor(ndb.Model):
	"""Models a sensor in an wukong application"""
	name = ndb.StringProperty()
	application_key = ndb.KeyProperty(kind=WKApplication)

	@staticmethod
	def get_sensor_data1(application_name):
		"""Get all sensors for the application first, then get all samples per sensor.
		First attempt. It works, but causes multiple queries, which probably isn't efficient if we want all samples."""
		sensors = WKSensor.query(WKSensor.application_key==WKApplication.key_for_application(application_name))

		# TODO: There must be a better way to do this? Can't I get all sensors and values in one query?
		for sensor in sensors:
			sensor.samples = WKSample.query(ancestor=sensor.key).order(WKSample.time).fetch()
		return sensors

	# @staticmethod
	# def get_sensor_data2(application_name):
	# 	"""Get everything for this application at once. Probably not a good idea if it's too much data, but
	# 	if we do want everything, this should be more efficient than the previous query.
	# 	The processing to change the flat list into a hierarchy of sensors and samples should be fast enough
	# 	since it's just two simple passes over the list"""
	# 	query = ndb.gql("SELECT * WHERE ANCESTOR IS :1 ORDER BY __key__", WKApplication.key_for_application(application_name))

	# 	# Would this be sorted by __key__ as well? I'm not sure how to force that using this syntax.
	# 	# query = ndb.Query(ancestor=WKApplication.key_for_application(application_name))

	# 	# At this point we get a list containing the Application object first, followed by sensors
	# 	# with all the samples for each sensor directly after that sensor object. (since it's sorted on __key__)
	# 	# This means we don't need to search the list for the matching sensor, but can just use the last one we came across.
	# 	current_sensor = None
	# 	results = query.fetch()
	# 	print results
	# 	for result in results:
	# 		if isinstance(result, WKSensor):
	# 			current_sensor = result
	# 			current_sensor.samples = []
	# 		if isinstance(result, WKSample):
	# 			current_sensor.samples.append(result)

	# 	sensors = [result for result in results if isinstance(result, WKSensor)] # Just return the sensors, samples are now in a sublist
	# 	return sensors

	# @staticmethod
	# def get_sensor_data3(application_name):
	# 	"""Trying something inbetween: get all sensors first, then get all samples with ancestor in those sensors"""
	# 	sensors = WKSensor.query(ancestor=WKApplication.key_for_application(application_name)).fetch()
	# 	samples = WKSample.query(ancestor=WKApplication.key_for_application(application_name)).fetch()

	# 	# This works, but wasn't really was I was looking for. I seems you can't select from multiple ancestors
	# 	# (I wanted to do something like "'ANCESTOR IN :1', [x.key for x in sensors]")
	# 	for sensor in sensors:
	# 		sensor.samples = [sample for sample in samples if sample.key.parent() == sensor.key]

	# 	return sensors

class WKSample(ndb.Model):
	"""Models a single measurement in a wukong application"""
	value = ndb.IntegerProperty()
	time = ndb.DateTimeProperty(auto_now_add=True)

	@staticmethod
	def logSample(application_name, sensor_name, value, time=None):
		application = WKApplication.get_or_insert(application_name,
													name=application_name)

		sensor = WKSensor.get_or_insert(sensor_name,
										application_key=application.key,
										name=sensor_name)

		if time==None:
			sample = WKSample(parent=sensor.key,
							value = int(value))
		else:
			sample = WKSample(parent=sensor.key,
							value = int(value),
							time = time)
		sample.put()

class SensorLog(webapp2.RequestHandler):

	def get(self):
		application_name = self.request.get('application')

		sensors = WKSensor.get_sensor_data1(application_name)

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

		WKSample.logSample(application_name, sensor_name, value)

		query_params = {'application': application_name}
		self.redirect('/sensorlog?' + urllib.urlencode(query_params))

class CreateTestData(webapp2.RequestHandler):
	@ndb.transactional(xg=True)
	def createWithCrossGroupTransaction(self):
		application_name = 'testapp'
		time = datetime.datetime.now()
		time += datetime.timedelta(days=-1)
		for sensor_name in ['a', 'b', 'c']:
			for value in range(100):
				WKSample.logSample(application_name, sensor_name, value, time=time)
				time += datetime.timedelta(minutes=1)
		query_params = {'application': 'testapp'}
		self.redirect('/sensorlog?' + urllib.urlencode(query_params))

	def get(self):
		self.createWithCrossGroupTransaction()
		query_params = {'application': 'testapp'}
		self.redirect('/sensorlog?' + urllib.urlencode(query_params))

app = webapp2.WSGIApplication([('/sensorlog', SensorLog),
								('/logsample', LogSample),
								('/createtestdata', CreateTestData)],
                              debug=True)

