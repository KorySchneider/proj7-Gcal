import flask
from flask import render_template
from flask import request
from flask import url_for
import uuid

import json
import logging

# Date handling
import arrow # Replacement for datetime, based on moment.js
# import datetime # But we still need time
from dateutil import tz  # For interpreting local times


# OAuth2  - Google library implementation for convenience
from oauth2client import client
import httplib2   # used in oauth2 flow

# Google API for services
from apiclient import discovery

###
# Globals
###
import CONFIG
import secrets.admin_secrets  # Per-machine secrets
import secrets.client_secrets # Per-application secrets

app = flask.Flask(__name__)
app.debug=CONFIG.DEBUG
app.logger.setLevel(logging.DEBUG)
app.secret_key=CONFIG.secret_key

SCOPES = 'https://www.googleapis.com/auth/calendar.readonly'
CLIENT_SECRET_FILE = secrets.admin_secrets.google_key_file
APPLICATION_NAME = 'MeetMe class project'

#############################
#
#  Pages (routed from URLs)
#
#############################

@app.route("/")
@app.route("/index")
def index():
  app.logger.debug("Entering index")
  if 'begin_date' not in flask.session:
    init_session_values()
  return render_template('index.html')

@app.route("/choose")
def choose():
    ## We'll need authorization to list calendars
    app.logger.debug("Checking credentials for Google calendar access")
    credentials = valid_credentials()
    if not credentials:
      app.logger.debug("Redirecting to authorization")
      return flask.redirect(flask.url_for('oauth2callback'))

    gcal_service = get_gcal_service(credentials)
    app.logger.debug("Returned from get_gcal_service")
    flask.session['calendars'] = list_calendars(gcal_service)

    #for cal in flask.session['calendars']:
    #    app.logger.debug(json.dumps(str(cal), indent=2, sort_keys=True))

    return render_template('index.html')

@app.route("/events")
def events():
    app.logger.debug("Entering events page")
    return render_template('events.html')

####
#
#  Google calendar authorization:
#      Returns us to the main /choose screen after inserting
#      the calendar_service object in the session state.  May
#      redirect to OAuth server first, and may take multiple
#      trips through the oauth2 callback function.
#
#  Protocol for use ON EACH REQUEST:
#     First, check for valid credentials
#     If we don't have valid credentials
#         Get credentials (jump to the oauth2 protocol)
#         (redirects back to /choose, this time with credentials)
#     If we do have valid credentials
#         Get the service object
#
#  The final result of successful authorization is a 'service'
#  object.  We use a 'service' object to actually retrieve data
#  from the Google services. Service objects are NOT serializable ---
#  we can't stash one in a cookie.  Instead, on each request we
#  get a fresh serivce object from our credentials, which are
#  serializable.
#
#  Note that after authorization we always redirect to /choose;
#  If this is unsatisfactory, we'll need a session variable to use
#  as a 'continuation' or 'return address' to use instead.
#
####

def valid_credentials():
    """
    Returns OAuth2 credentials if we have valid
    credentials in the session.  This is a 'truthy' value.
    Return None if we don't have credentials, or if they
    have expired or are otherwise invalid.  This is a 'falsy' value.
    """
    if 'credentials' not in flask.session:
      return None

    credentials = client.OAuth2Credentials.from_json(
        flask.session['credentials'])

    if (credentials.invalid or
        credentials.access_token_expired):
      return None
    return credentials


def get_gcal_service(credentials):
  """
  We need a Google calendar 'service' object to obtain
  list of calendars, busy times, etc.  This requires
  authorization. If authorization is already in effect,
  we'll just return with the authorization. Otherwise,
  control flow will be interrupted by authorization, and we'll
  end up redirected back to /choose *without a service object*.
  Then the second call will succeed without additional authorization.
  """
  app.logger.debug("Entering get_gcal_service")
  http_auth = credentials.authorize(httplib2.Http())
  service = discovery.build('calendar', 'v3', http=http_auth)
  return service

@app.route('/oauth2callback')
def oauth2callback():
  """
  The 'flow' has this one place to call back to.  We'll enter here
  more than once as steps in the flow are completed, and need to keep
  track of how far we've gotten. The first time we'll do the first
  step, the second time we'll skip the first step and do the second,
  and so on.
  """
  app.logger.debug("Entering oauth2callback")
  flow =  client.flow_from_clientsecrets(
      CLIENT_SECRET_FILE,
      scope= SCOPES,
      redirect_uri=flask.url_for('oauth2callback', _external=True))
  ## Note we are *not* redirecting above.  We are noting *where*
  ## we will redirect to, which is this function.

  ## The *second* time we enter here, it's a callback
  ## with 'code' set in the URL parameter.  If we don't
  ## see that, it must be the first time through, so we
  ## need to do step 1.
  if 'code' not in flask.request.args:
    auth_uri = flow.step1_get_authorize_url()
    return flask.redirect(auth_uri)
    ## This will redirect back here, but the second time through
    ## we'll have the 'code' parameter set
  else:
    ## It's the second time through ... we can tell because
    ## we got the 'code' argument in the URL.
    auth_code = flask.request.args.get('code')
    credentials = flow.step2_exchange(auth_code)
    flask.session['credentials'] = credentials.to_json()
    ## Now I can build the service and execute the query,
    ## but for the moment I'll just log it and go back to
    ## the main screen
    return flask.redirect(flask.url_for('choose'))

#####
#
#  Option setting:  Buttons or forms that add some
#     information into session state.  Don't do the
#     computation here; use of the information might
#     depend on what other information we have.
#   Setting an option sends us back to the main display
#      page, where we may put the new information to use.
#
#####

@app.route('/setrange', methods=['POST'])
def setrange():
    """
    User chose a date range and time range with the bootstrap daterange widget.
    """
    app.logger.debug("Entering setrange")
    daterange = request.form.get('daterange')
    flask.session['daterange'] = daterange
    daterange_parts = daterange.split()

    flask.session['begin_date'] = interpret_date(daterange_parts[0])
    flask.session['end_date'] = interpret_date(daterange_parts[2])
    flask.session['begin_time'] = interpret_time(request.form.get('begin_time'))
    flask.session['end_time'] = interpret_time(request.form.get('end_time'))

    return flask.redirect(flask.url_for("choose"))

@app.route('/getevents', methods=['POST'])
def getevents():
    """
    User has selected which calendars are relevant, this function puts relevant events into flask.session['calendars']
    """
    app.logger.debug("Entering getevents")
    calendars = list(dict(request.form).keys())
    app.logger.debug("Calendars to get events for: {}".format(calendars))

    credentials = valid_credentials()
    gcal_service = get_gcal_service(credentials)

    events = []
    for i in range(0, len(calendars)):
        for cal in flask.session['calendars']:
            if calendars[i] == cal['summary']:
                events.extend(list_events(gcal_service, cal['id']))
    flask.session['events'] = events
    return flask.redirect(flask.url_for('events'))

####
#
#   Initialize session variables
#
####

def init_session_values():
    """
    Start with some reasonable defaults for date and time ranges.
    Note this must be run in app context ... can't call from main.
    """
    # Default date span = tomorrow to 1 week from now
    now = arrow.now('local')     # We really should be using tz from browser
    tomorrow = now.replace(days=+1)
    nextweek = now.replace(days=+7)
    flask.session["begin_date"] = tomorrow.floor('day').isoformat()
    flask.session["end_date"] = nextweek.ceil('day').isoformat()
    flask.session["daterange"] = "{} - {}".format(
        tomorrow.format("MM/DD/YYYY"),
        nextweek.format("MM/DD/YYYY"))
    # Default time span each day, 8 to 5
    flask.session["begin_time"] = interpret_time("9am")
    flask.session["end_time"] = interpret_time("5pm")

def interpret_time( text ):
    """
    Read time in a human-compatible format and
    interpret as ISO format with local timezone.
    May throw exception if time can't be interpreted. In that
    case it will also flash a message explaining accepted formats.
    """
    app.logger.debug("Decoding time '{}'".format(text))
    time_formats = ["ha", "h:mma",  "h:mm a", "H:mm"]
    try:
        as_arrow = arrow.get(text, time_formats).replace(tzinfo=tz.tzlocal())
        as_arrow = as_arrow.replace(year=2016) #HACK see below
    except:
        flask.flash("Time '{}' didn't match accepted formats 13:30 or 1:30pm"
              .format(text))
        raise
    return as_arrow.isoformat()
    #HACK #Workaround
    # isoformat() on raspberry Pi does not work for some dates
    # far from now.  It will fail with an overflow from time stamp out
    # of range while checking for daylight savings time.  Workaround is
    # to force the date-time combination into the year 2016, which seems to
    # get the timestamp into a reasonable range. This workaround should be
    # removed when Arrow or Dateutil.tz is fixed.
    # FIXME: Remove the workaround when arrow is fixed (but only after testing
    # on raspberry Pi --- failure is likely due to 32-bit integers on that platform)


def interpret_date( text ):
    """
    Convert text of date to ISO format used internally,
    with the local time zone.
    """
    try:
      as_arrow = arrow.get(text, "MM/DD/YYYY").replace(
          tzinfo=tz.tzlocal())
    except:
        flask.flash("Date '{}' didn't fit expected format 12/31/2001")
        raise
    return as_arrow.isoformat()

def next_day(isotext):
    """
    ISO date + 1 day (used in query to Google calendar)
    """
    as_arrow = arrow.get(isotext)
    return as_arrow.replace(days=+1).isoformat()

####
#
#  Functions (NOT pages) that return some information
#
####

def list_calendars(service):
    """
    Given a google 'service' object, return a list of
    calendars.  Each calendar is represented by a dict.
    The returned list is sorted to have
    the primary calendar first, and selected (that is, displayed in
    Google Calendars web app) calendars before unselected calendars.
    """
    app.logger.debug("Entering list_calendars")
    calendar_list = service.calendarList().list().execute()["items"]
    result = [ ]
    for cal in calendar_list:
        kind = cal["kind"]
        id = cal["id"]
        if "description" in cal:
            desc = cal["description"]
        else:
            desc = "(no description)"
        summary = cal["summary"]
        # Optional binary attributes with False as default
        selected = ("selected" in cal) and cal["selected"]
        primary = ("primary" in cal) and cal["primary"]


        result.append(
          { "kind": kind,
            "id": id,
            "summary": summary,
            "selected": selected,
            "primary": primary
            })
    return sorted(result, key=cal_sort_key)

def cal_sort_key( cal ):
    """
    Sort key for the list of calendars:  primary calendar first,
    then other selected calendars, then unselected calendars.
    (" " sorts before "X", and tuples are compared piecewise)
    """
    if cal["selected"]:
       selected_key = " "
    else:
       selected_key = "X"
    if cal["primary"]:
       primary_key = " "
    else:
       primary_key = "X"
    return (primary_key, selected_key, cal["summary"])

def list_events(service, cal_id):
    app.logger.debug("Entering list_events")
    event_list = []
    page_token = None
    while True:
        events = service.events().list(calendarId=cal_id, pageToken=page_token, timeMin=flask.session['begin_time'], timeMax=flask.session['end_date'], showDeleted=False, singleEvents=True).execute()
        for event in events['items']:
            if 'transparency' not in event.keys():
                # check to see if event is within time constraints
                try:
                    ev_start_date = str(arrow.get(event['start']['dateTime'])).split('T')[0]
                    ev_end_date = str(arrow.get(event['end']['dateTime'])).split('T')[0]
                    ev_start_time = str(arrow.get(event['start']['dateTime'])).split('T')[1].split('-')[0]
                    ev_end_time = str(arrow.get(event['end']['dateTime'])).split('T')[1].split('-')[0]
                except KeyError:
                    if 'date' in event['start'].keys(): # handle all day events (e.g. birthdays)
                        continue
                    else:
                        raise
                if ev_start_date >= flask.session['begin_date'].split('T')[0] and ev_end_date <= flask.session['end_date'].split('T')[0]:
                    if ev_start_time >= flask.session['begin_time'].split('T')[1].split('-')[0] and ev_end_time <= flask.session['end_time'].split('T')[1].split('-')[0]:
                        event_list.append(event)
        page_token = events.get('nextPageToken')
        if not page_token:
            break
    return event_list

#################
#
# Functions used within the templates
#
#################

@app.template_filter( 'fmtdate' )
def format_arrow_date( date ):
    try:
        normal = arrow.get( date )
        return normal.format("ddd MM/DD/YYYY")
    except:
        return "(bad date)"

@app.template_filter( 'fmttime' )
def format_arrow_time( time ):
    try:
        normal = arrow.get( time )
        return normal.format("HH:mm")
    except:
        return "(bad time)"

@app.template_filter( 'fmtdatetime' )
def format_arrow_datetime( datetime ):
    try:
        normal = arrow.get(datetime)
        return normal.format("ddd MM/DD/YYYY HH:mm")
    except:
        return "(bad datetime)"

#############


if __name__ == "__main__":
  # App is created above so that it will
  # exist whether this is 'main' or not
  # (e.g., if we are running under green unicorn)
  app.run(port=CONFIG.PORT,host="0.0.0.0")

