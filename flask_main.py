import flask
from flask import render_template
from flask import request
from flask import url_for
from flask import jsonify
import uuid

import json
import logging
from operator import itemgetter

# Date handling
import arrow # Replacement for datetime, based on moment.js
# import datetime # But we still need time
from dateutil import tz  # For interpreting local times


# OAuth2  - Google library implementation for convenience
from oauth2client import client
import httplib2   # used in oauth2 flow

# Google API for services
from apiclient import discovery

# Database interaction
import db_functions
db_functions.connect() # initialize db connection

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
    app.logger.debug("Entering index page")
    return render_template('index.html')

@app.route("/create")
def create():
  app.logger.debug("Entering create page")
  if 'begin_date' not in flask.session:
    init_session_values()
  return render_template('create.html')

@app.route("/calendars")
def calendars():
    app.logger.debug("Entering calendars page")
    credentials = valid_credentials()
    if not credentials:
      return flask.redirect(flask.url_for('oauth2callback'))

    gcal_service = get_gcal_service(credentials)
    flask.session['calendars'] = list_calendars(gcal_service)
    return render_template('calendars.html')

@app.route("/events")
def events():
    app.logger.debug("Entering events page")
    return render_template('events.html')

@app.route("/freetimes")
def freetimes():
    app.logger.debug("Entering freetimes page")
    return render_template('freetimes.html')

@app.route("/finish")
def finish():
    app.logger.debug("Entering finish page")
    return render_template('finish.html')

@app.route("/add/<meeting_id>")
def add_user(meeting_id):
    app.logger.debug("Entering add_user with meeting_id {}".format(meeting_id))
    flask.session['meeting_id'] = meeting_id
    flask.session['user_id'] = str(uuid.uuid4())
    flask.session['meeting_range'] = db_functions.get_meeting_range(meeting_id)
    return render_template('adduser.html')

###
# Ajax handlers
###

@app.route('/_calc_free_times')
def _calc_free_times():
    app.logger.debug("Entering _calc_free_times")
    def normalize(events):
        """
        Merges overlapping events from a list of events ordered by start times
        """
        normalized = []
        cur = events[0]
        for event in events[1:]:
            if event['start'] > cur['end']: # not overlapping
                normalized.append(cur)
                cur = event
            else:
                cur = merge_events(cur, event)
        normalized.append(cur)
        return normalized

    def merge_events(e1, e2, summary=""):
        """
        Merge two events
        """
        if summary == "":
            summary = e1['summary'] + " + " + e2['summary']
        start = min(e1['start'], e2['start'])
        end = max(e1['end'], e2['end'])
        return { 'start': start, 'end': end, 'summary': summary }

    def separate_free_times(interval, i_list):
        """
        If a freetime extends from the end of one day to the beginning of the next,
        split it into two freetimes: one that goes to then end of the time range on
        the first day, and another that goes from the start of the next day until the
        next event. Repeats recursively on the second freetime (to handle freetimes
        that span multiple days).
        """
        if str(arrow.get(interval['end']).date()) > str(arrow.get(interval['start']).date()):
            s = arrow.get(interval['start'])
            i1_end = arrow.get(meeting_range['end_time']).replace(year=s.year, month=s.month, day=s.day).isoformat()
            i2_start = arrow.get(meeting_range['begin_time']).replace(year=s.year, month=s.month, day=s.day).replace(days=+1).isoformat()

            i1 = { 'start': interval['start'], 'end': i1_end }
            i2 = { 'start': i2_start, 'end': interval['end'] }

            if not str(arrow.get(interval['start']).time()) == str(arrow.get(i1_end).time()):
                if not str(arrow.get(i1['start']).time()) > str(arrow.get(i1['end']).time()):
                    i_list.append(i1)

            if str(arrow.get(i2_start).time()) > str(arrow.get(interval['end']).time()) or str(arrow.get(i2_start).time()) == str(arrow.get(interval['end']).time()):
                return
            else:
                separate_free_times(i2, i_list)
        else:
            i_list.append(interval)
    # end functions for this function

    meeting_id = request.args.get('meeting_id')
    meeting_range = db_functions.get_meeting_range(meeting_id)
    events = db_functions.get_all_events(meeting_id)
    if len(events) == 0:
        return jsonify(result = { 'free_times': None })
    sorted_events = sorted(events, key=itemgetter('start'))
    normalized_events = normalize(sorted_events)

    free_times = []
    for i in range(len(normalized_events) - 1):
        if normalized_events[i]['end'] < normalized_events[i+1]['start']:
            free = { 'start': normalized_events[i]['end'], 'end': normalized_events[i+1]['start'] }
            free_times.append(free)

    start_time = str(arrow.get(meeting_range['begin_time']).time()).split(':')
    initial_free_time = { 'start': arrow.get(meeting_range['begin_date']).replace(hour=int(start_time[0]), minute=int(start_time[1]), second=int(start_time[2])).isoformat(),
                          'end': normalized_events[0]['start'] }
    end_time = str(arrow.get(meeting_range['end_time']).time()).split(':')
    final_free_time = { 'start': normalized_events[-1]['end'],
                        'end': arrow.get(meeting_range['end_date']).replace(hour=int(end_time[0]), minute=int(end_time[1]), second=int(end_time[2])).isoformat() }
    free_times.insert(0, initial_free_time)
    free_times.append(final_free_time)

    split_free_times = []
    for ft in free_times:
        separate_free_times(ft, split_free_times)

    return jsonify(result = { 'free_times': split_free_times })

@app.route('/_get_events')
def _get_events():
    """
    Get user events from database
    """
    app.logger.debug("Entering _get_events handler")
    meeting_id = request.args.get('meeting_id')
    user_id = request.args.get('user_id')
    flask.session['meeting_id'] = meeting_id
    flask.session['user_id'] = user_id
    events = db_functions.get_user_events(meeting_id, user_id)
    return jsonify(events = events)

@app.route('/_get_meeting_info')
def _get_meeting_info():
    """
    Get meeting info to display when adding user
    """
    app.logger.debug("Entering _get_meeting_info handler")
    meeting = db_functions.get_meeting(flask.session['meeting_id'])
    meeting_info = { 'creator': meeting['creator_name'],
                     'title': meeting['meeting_title'],
                     'length': meeting['meeting_length'],
                     'desc': meeting['meeting_desc'] }
    return jsonify(meeting_info = meeting_info)

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
    return flask.redirect(flask.url_for('calendars'))

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
    User chose a date range and time range with the
    bootstrap daterange widget - create new meeting
    document in database, and set meeting & user
    IDs for current session.
    """
    app.logger.debug("Entering setrange")
    daterange = request.form.get('daterange')
    daterange_parts = daterange.split()

    flask.session['begin_date'] = interpret_date(daterange_parts[0])
    flask.session['end_date'] = interpret_date(daterange_parts[2])
    flask.session['begin_time'] = interpret_time(request.form.get('begin_time'))
    flask.session['end_time'] = interpret_time(request.form.get('end_time'))

    # Create empty meeting in database
    meeting_title = request.form.get('meeting-title')
    meeting_desc = request.form.get('meeting-desc')
    meeting_length = { 'hours': request.form.get('meeting-hrs'), 'minutes': request.form.get('meeting-mins') }
    meeting_id = str(uuid.uuid4())
    user_id = str(uuid.uuid4())
    flask.session['meeting_id'] = meeting_id
    flask.session['user_id'] = user_id
    creator_name = request.form.get('creator-name')
    meeting_range = { 'begin_date': flask.session['begin_date'], 'end_date': flask.session['end_date'],
                      'begin_time': flask.session['begin_time'], 'end_time': flask.session['end_time'] }
    db_functions.create_meeting(meeting_id, meeting_range, meeting_title, meeting_desc, meeting_length, creator_name)

    return flask.redirect(flask.url_for("calendars"))

@app.route('/getevents', methods=['POST'])
def getevents():
    """
    Get user events from google calendar
    """
    app.logger.debug("Entering getevents")
    def format_events(events):
        """
        Format events for storage in database.
        A formatted event looks like:
        {
          id: eventid,
          summary: string,
          start: datetime,
          end: datetime,
        }
        """
        app.logger.debug('Entering format_events')
        formatted_events = []
        for event in events:
            fevent = {key:event[key] for key in ['id', 'summary']}
            if 'date' in event['start'].keys():
                fevent['start'] = arrow.get(event['start']['date']).isoformat()
            else:
                fevent['start'] = event['start']['dateTime']
            if 'date' in event['end'].keys():
                fevent['end'] = arrow.get(event['end']['date']).replace(days=+1).isoformat()
            else:
                fevent['end'] = event['end']['dateTime']

            formatted_events.append(fevent)
        return formatted_events

    calendars = list(dict(request.form).keys())

    credentials = valid_credentials()
    gcal_service = get_gcal_service(credentials)

    events = []
    for i in range(0, len(calendars)):
        for cal in flask.session['calendars']:
            if calendars[i] == cal['summary']:
                events.extend(list_events(gcal_service, cal['id']))

    formatted_events = format_events(events)
    db_functions.add_user_with_events(flask.session['meeting_id'],
                                      flask.session['user_id'],
                                      formatted_events)

    return flask.redirect(flask.url_for('events'))

@app.route('/remove_events', methods=['POST'])
def remove_events():
    app.logger.debug("Entering remove_events")
    events_to_remove = list(dict(request.form).keys()) # list of event IDs
    meeting = db_functions.get_meeting(flask.session['meeting_id'])
    #for event in events_to_remove:
    for user in meeting['users']:
        if user['user_id'] == flask.session['user_id']:
            user['events'][:] = [d for d in user['events'] if d.get('id') not in events_to_remove]
        ## FIXME the remove_event db method does not seem to work in the context of the app.
        ##  I have replaced the call below with the logic above for now.
        #db_functions.remove_event(flask.session['meeting_id'], flask.session['user_id'], event)

    db_functions.replace_meeting(flask.session['meeting_id'], meeting)
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
    # Default time span each day, 9 to 5
    flask.session["begin_time"] = interpret_time("9am")
    flask.session["end_time"] = interpret_time("5pm")

def interpret_time( text ):
    """
    Read time in a human-compatible format and
    interpret as ISO format with local timezone.
    May throw exception if time can't be interpreted. In that
    case it will also flash a message explaining accepted formats.
    """
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
        #kind = cal["kind"]
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
          { "id": id,
            #"kind": kind,
            "selected": selected,
            "primary": primary,
            "summary": summary
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

    meeting_range = db_functions.get_meeting_range(flask.session['meeting_id'])

    begin_date = arrow.get(meeting_range['begin_date'])
    begin_time = arrow.get(meeting_range['begin_time'])
    time_min = begin_time.replace(year=begin_date.year, month=begin_date.month, day=begin_date.day).isoformat()
    end_time = arrow.get(meeting_range['end_time'])
    end_date = arrow.get(meeting_range['end_date'])
    time_max = end_time.replace(year=end_date.year, month=end_date.month, day=end_date.day).isoformat()

    while True:
        events = service.events().list(calendarId=cal_id,
                                       pageToken=page_token,
                                       timeMin=time_min,
                                       timeMax=time_max,
                                       showDeleted=False,
                                       singleEvents=True).execute()

        meeting_start_date = str(arrow.get(meeting_range['begin_date']).date())
        meeting_end_date =   str(arrow.get(meeting_range['end_date']).date())
        meeting_start_time = str(arrow.get(meeting_range['begin_time']).time())
        meeting_end_time =   str(arrow.get(meeting_range['end_time']).time())

        for event in events['items']:
            if 'transparency' not in event.keys():
                try:
                    ev_start_date = str(arrow.get(event['start']['dateTime']).date())
                    ev_end_date = str(arrow.get(event['end']['dateTime']).date())
                    ev_start_time = str(arrow.get(event['start']['dateTime']).time())
                    ev_end_time = str(arrow.get(event['end']['dateTime']).time())
                except KeyError:
                    if 'date' in event['start'].keys(): # all-day events
                        ev_start_date = event['start']['date']
                        ev_end_date = event['end']['date']

                        if (ev_start_date <= meeting_start_date and ev_end_date >= meeting_start_date) or (ev_end_date >= meeting_end_date and ev_start_date <= meeting_end_date) or (ev_start_date >= meeting_start_date and ev_end_date <= meeting_end_date):
                            start = arrow.get(event['start']['date']).isoformat()
                            end = arrow.get(event['end']['date']).isoformat()
                            del event['start']['date']
                            del event['end']['date']
                            event['start'] = { 'dateTime': start }
                            event['end'] = { 'dateTime': end }
                            event_list.append(event)
                        continue
                    else:
                        app.logger.debug('Could not parse event: {}'.format(event))
                        raise

                # check to see if event is within time constraints...
                if ev_start_date <= meeting_end_date and ev_start_date >= meeting_start_date: # is within date range
                    if ev_start_time >= meeting_start_time and ev_end_time <= meeting_end_time: # and is within time range
                        event_list.append(event)
                    elif ev_start_time <= meeting_start_time and ev_end_time >= meeting_start_time: # or overlaps begin time
                        event_list.append(event)
                    elif ev_end_time >= meeting_end_time and ev_start_time <= meeting_end_time: # or overlaps end time
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

