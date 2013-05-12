import cgi
import datetime
import urllib
import webapp2
import os
import urllib
import jinja2

from google.appengine.api import users
from google.appengine.ext import db


JINJA_ENVIRONMENT = jinja2.Environment(
    loader=jinja2.FileSystemLoader(os.path.dirname(__file__)),
    extensions=['jinja2.ext.autoescape'])

MAIN_PAGE_FOOTER_TEMPLATE = """\
    <form action="/sign?%s" method="post">
      <div><textarea name="content" rows="3" cols="60"></textarea></div>
      <div><input type="submit" value="Sign Guestbook"></div>
    </form>
    <hr>
    <form>Guestbook name: <input value="%s" name="guestbook_name">
    <input type="submit" value="switch"></form>
  </body>
</html>
"""

class Greeting(db.Model):
	"""Models an individual Guestbook entry with author, content, and date."""
	author = db.StringProperty()
	content = db.StringProperty(multiline=True)
	date = db.DateTimeProperty(auto_now_add=True)

def guestbook_key(guestbook_name=None):
	"""Constructs a Datastore key for a Guestbook entity with guestbook_name."""
	return db.Key.from_path('Guestbook', guestbook_name or 'default_guestbook')

class MainPage(webapp2.RequestHandler):
	def get(self):
		guestbook_name = self.request.get('guestbook_name')
		# Ancestor Queries, as shown here, are strongly consistent with the High
		# Replication Datastore. Queries that span entity groups are eventually
		# consistent. If we omitted the ancestor from this query there would be
		# a slight chance that Greeting that had just been written would not
		# show up in a query.

		greetings_query = Greeting.query(
								ancestor=guestbook_key(guestbook_name)).order(-Greeting.date)
		greetings = greetings_query.fetch(10)

		if users.get_current_user():
			url = users.create_logout_url(self.request.uri)
			url_linktext = "Logout"
		else:
			url = users.create_login_url(self.request.uri)
			url_linktext = "Login"

		template_values = {'greetings': greetings,
							'guestbook_name': url.urlencode(guestbook_name),
							'url': url,
							'url_linktext': url_linktext}

		template = JINJA_ENVIRONMENT.get_template('index.html')
		self.response.write(template.render(template_values))

class Guestbook(webapp2.RequestHandler):
    def post(self):
		# We set the same parent key on the 'Greeting' to ensure each greeting
		# is in the same entity group. Queries across the single entity group
		# will be consistent. However, the write rate to a single entity group
		# should be limited to ~1/second.

		guestbook_name = self.request.get('guestbook_name')
		greeting = Greeting(parent=guestbook_key(guestbook_name))

		if users.get_current_user():
			greeting.author = users.get_current_user().nickname()

		print users.get_current_user().nickname()

		greeting.content = self.request.get('content')
		print greeting
		greeting.put()

		query_params = {'guestbook_name': guestbook_name}
		self.redirect('/?' + urllib.urlencode(query_params))


app = webapp2.WSGIApplication([('/', MainPage),
								('/sign', Guestbook)],
                              debug=True)
