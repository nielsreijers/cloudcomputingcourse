import cgi
import time
import datetime
import urllib
import webapp2
import os
import jinja2
import operator
import mapreduce
import logging
import pickle

from google.appengine.api import users
from google.appengine.ext import ndb
from google.appengine.api import taskqueue
from google.appengine.api import runtime

from mapreduce import base_handler
from mapreduce import mapreduce_pipeline

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

class WKLog(ndb.Model):
	message = ndb.StringProperty()
	time = ndb.DateTimeProperty(auto_now_add=True)

	@staticmethod
	def log(message):
		entry = WKLog(message=message)
		entry.put()

	@staticmethod
	def get_log():
		entries = WKLog.query().order(WKLog.time).fetch()
		return entries

	@staticmethod
	def clear_log():
		keys = WKLog.query().fetch(keys_only=True)
		ndb.delete_multi(keys)


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
	# 	sensors = WKSensor.query(WKSensor.application_key=WKApplication.key_for_application(application_name)).fetch()
	# 	samples = WKSample.query(ancestor=WKApplication.key_for_application(application_name)).fetch()

	# 	# This works, but wasn't really was I was looking for. I seems you can't select from multiple ancestors
	# 	# (I wanted to do something like "'ANCESTOR IN :1', [x.key for x in sensors]")
	# 	for sensor in sensors:
	# 		sensor.samples = [sample for sample in samples if sample.key.parent() == sensor.key]

	# 	return sensors

	@staticmethod
	def get_sensor_data4(application_name):
		"""Get the sensor data asynchonously"""
		sensors = WKSensor.query(WKSensor.application_key==WKApplication.key_for_application(application_name))

		# TODO: There must be a better way to do this? Can't I get all sensors and values in one query?
		sample_futures = {}
		for sensor in sensors:
			sample_futures[sensor.key] = WKSample.query(ancestor=sensor.key).order(WKSample.time).fetch_async()
		for sensor in sensors:
			sensor.samples = sample_futures[sensor.key].get_result()
		return sensors


class WKSample(ndb.Model):
	"""Models a single measurement in a wukong application"""
	value = ndb.IntegerProperty()
	time = ndb.DateTimeProperty(auto_now_add=True)

	@staticmethod
	def logSample(application_name, sensor_name, value, time=None):
		application = WKApplication.get_or_insert(application_name,
													name=application_name)

		sensor = WKSensor.get_or_insert(str(application.key) + "/" + sensor_name,
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

class WKSensorSummary(ndb.Model):
	"""Contains a summary of the sensor data, currently just avg/min/max"""
	sensor_key = ndb.KeyProperty(kind=WKSensor)
	avg_value = ndb.FloatProperty()
	min_value = ndb.IntegerProperty()
	max_value = ndb.IntegerProperty()
	min_value_at = ndb.DateTimeProperty()
	max_value_at = ndb.DateTimeProperty()
	calculated_at = ndb.DateTimeProperty(auto_now_add=True)

class SensorLog(webapp2.RequestHandler):
	def get(self):
		application_name = self.request.get('application', 'testapp')

		start_time = time.time()
		sensors = WKSensor.get_sensor_data4(application_name)
		for sensor in sensors:
			summaries = WKSensorSummary.query(WKSensorSummary.sensor_key==sensor.key).order(-WKSensorSummary.calculated_at).fetch(1)
			if summaries:
				sensor.summary = summaries[0]
			else:
				sensor.summary = None
		elapsed_time = time.time() - start_time

		if users.get_current_user():
			user_text = "Logged in as: " + users.get_current_user().email()
			url = users.create_logout_url(self.request.uri)
			url_linktext = "Logout"
		else:
			user_text = "Not logged in"
			url = users.create_login_url(self.request.uri)
			url_linktext = "Login"

		log_entries = WKLog.get_log()

		template_values = {'sensors': sensors,
						'application': application_name,
						'elapsed_time': elapsed_time,
						'current_time': datetime.datetime.now(),
						'user_text': user_text,
						'url': url,
						'url_linktext': url_linktext,
						'log_entries': log_entries}
		template = JINJA_ENVIRONMENT.get_template('sensor_log.html')
		self.response.write(template.render(template_values))

	def post(self):
		if self.request.get('run_directly'):
			WKLog.log("Starting sensor summary mapreduce pipeline.")
			pipeline = SensorSummaryPipeline()
			pipeline.start()
			self.redirect(pipeline.base_path + "/status?root=" + pipeline.pipeline_id)
			return
		elif self.request.get('start_task_queue'):
			WKLog.log("Starting task queue for map reduce task.")
			MapReduceTaskQueue.purge()
			MapReduceTaskQueue.add_new_task()
		elif self.request.get('stop_task_queue'):
			WKLog.log("Stopping task queue for map reduce task.")
			MapReduceTaskQueue.purge()
		elif self.request.get('clear_log'):
			WKLog.clear_log()
		self.redirect(self.request.url)


class MapReduceTaskQueue(webapp2.RequestHandler):
	@staticmethod
	def purge():
		WKLog.log("Purging queue")
		queue = taskqueue.Queue(name='sensor-summary-queue')
		queue.purge()


	@staticmethod
	def add_new_task(eta=None):
		task = None
		if eta:
			task = taskqueue.Task(payload=None,
									url='/mapreducetaskqueue',
									eta=eta)
		else:
			task = taskqueue.Task(payload=None,
									url='/mapreducetaskqueue')			
		WKLog.log("Task scheduled with ETA %s" % (eta))
		task.add(queue_name='sensor-summary-queue')

	def post(self):
		WKLog.log("Starting sensor summary mapreduce pipeline from task queue.")
		pipeline = SensorSummaryPipeline()
		pipeline.start()
		WKLog.log("Scheduling new task for next run.")
		MapReduceTaskQueue.add_new_task(eta=datetime.datetime.now() + datetime.timedelta(hours=1))

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
	def createWithCrossGroupTransaction(self, application_name):
		time = datetime.datetime.now()
		time += datetime.timedelta(days=-1)
		for sensor_name in ['a', 'b', 'c', 'd2']:
			for value in range(1000):
				WKSample.logSample(application_name, sensor_name, value, time=time)
				time += datetime.timedelta(minutes=1)
		query_params = {'application': 'testapp'}
		self.redirect('/sensorlog?' + urllib.urlencode(query_params))

	def post(self):
		return self.get()

	def get(self):
		application_name = self.request.get('application', 'testapp')
		self.createWithCrossGroupTransaction(application_name)
		query_params = {'application': application_name}
		self.redirect('/sensorlog?' + urllib.urlencode(query_params))

def sensorsummary_map(data):
	"""Retrieve the sensor values that go with a sensor"""
	sensor_key = data
	ndb_sensor_key = ndb.Key(WKSensor, sensor_key.id_or_name())
	sensor = ndb_sensor_key.get()
	samples = WKSample.query(ancestor=sensor.key).fetch()
	logging.info("Sample class: %s", samples[0].__class__)
	reduce_key = sensor_key.id_or_name()
	for sample in samples:
		yield (reduce_key, pickle.dumps((sample.time, sample.value)))

def sensorsummary_reduce(key, values):
	"""Calculate avr, min and max for this sensor."""
	WKLog.log("Running reduce for sensor %s" % (key))

	ndb_sensor_key = ndb.Key(WKSensor, key)
	samples = [pickle.loads(x) for x in values]
	logging.info("Key: %s", ndb_sensor_key)
	logging.info("Key class: %s", ndb_sensor_key.__class__)
	logging.info("Number of samples: %s", len(samples))
	logging.info("Samples class: %s", samples.__class__)
	logging.info("Samples 1st element: %s", samples[0])
	logging.info("Samples 1st element class: %s", samples[0].__class__)
	sensor_values = [sample[1] for sample in samples]

	avg_value = sum(sensor_values)/len(sensor_values)
	min_value = min(sensor_values)
	min_value_at = next(x[0] for x in samples if x[1]==min_value)
	max_value = max(sensor_values)
	max_value_at = next(x[0] for x in samples if x[1]==max_value)

	summary = WKSensorSummary(sensor_key=ndb_sensor_key,
								avg_value=avg_value,
								min_value=min_value,
								min_value_at=min_value_at,
								max_value=max_value,
								max_value_at=max_value_at)
	yield summary.put()

class SensorSummaryPipeline(base_handler.PipelineBase):
	def run(self):
		output = yield mapreduce_pipeline.MapreducePipeline(
			"sensorsummary",
			"wukong-demo.sensorsummary_map",
			"wukong-demo.sensorsummary_reduce",
			"mapreduce.input_readers.DatastoreKeyInputReader",
			"mapreduce.output_writers.BlobstoreOutputWriter",
			mapper_params={
			    "entity_kind": "WKSensor",
			    "batch_size": 2
			},
			reducer_params={
			    "mime_type": "text/plain",
			},
			shards=16)
		# yield StoreOutput("Phrases", filekey, output)

class SensorSummaryBackend(webapp2.RequestHandler):
	def get(self):
		if (self.request.url.endswith('/_ah/start')):
			WKLog.log("Backend started: %s" % (self.request.url))
		else:
			WKLog.log("Backend received unknown request: %s" % (self.request.url))
def my_shutdown_hook():
	WKLog.log("Backend shutdown hook called")



app = webapp2.WSGIApplication([('/', SensorLog),
								('/sensorlog', SensorLog),
								('/logsample', LogSample),
								('/createtestdata', CreateTestData),
								('/mapreducetaskqueue', MapReduceTaskQueue),
								('/_ah/start', SensorSummaryBackend)],
                              debug=True)


runtime.set_shutdown_hook(my_shutdown_hook)
