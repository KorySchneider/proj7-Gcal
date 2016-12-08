import arrow

from pymongo import MongoClient
import secrets.admin_secrets
import secrets.client_secrets

MONGO_CLIENT_URL = "mongodb://{}:{}@{}:{}/{}".format(
    secrets.client_secrets.db_user,
    secrets.client_secrets.db_user_pw,
    secrets.admin_secrets.host,
    secrets.admin_secrets.port,
    secrets.client_secrets.db)

collection = None

def connect():
    """
    Establish connection with mongo database
    """
    global MONGO_CLIENT_URL
    global collection
    try:
        dbclient = MongoClient(MONGO_CLIENT_URL)
        db = getattr(dbclient, secrets.client_secrets.db)
        collection = db.meetings
        return collection
    except:
        print("Failure opening database. Is Mongo running? Correct password?")
        sys.exit(1)

def create_meeting(meeting_id, meeting_range, meeting_desc, meeting_length):
    """
    Create new meeting object in database
    """
    global collection
    return collection.insert({ '_id': meeting_id,
                                'created': arrow.now().isoformat(),
                                'users': [],
                                'meeting_range': meeting_range,
                                'meeting_desc': meeting_desc,
                                'meeting_length': meeting_length })

def replace_meeting(meeting_id, replacement_doc):
    """
    Replace a meeting document
    """
    global collection
    return collection.update({ '_id': meeting_id }, replacement_doc)

def get_meeting(meeting_id):
    """
    Return the entire meeting object
    """
    global collection
    return collection.find_one({ '_id': meeting_id })

def add_user_with_events(meeting_id, user_id, user_name, events):
    """
    Add an array of events to a meeting for a user
    """
    global collection
    return collection.update({ '_id': meeting_id },
            { '$push': { 'users': { 'user_id': user_id, 'user_name': user_name, 'events': events } } } )

def remove_event(meeting_id, user_id, event_id):
    """
    Remove one event from a meeting for a user
    """
    global collection
    return collection.update({ '_id': meeting_id, 'users.user_id': user_id },
            { '$pull': { 'users.$.events': { 'event_id': event_id } } } )

def get_user_events(meeting_id, user_id):
    """
    Get all events for one user
    """
    global collection
    meeting = collection.find_one({ '_id': meeting_id })
    for user in meeting['users']:
        if user['user_id'] == user_id:
            return user['events']

def get_all_events(meeting_id):
    """
    Get all events for all users
    """
    global collection
    meeting = collection.find_one({ '_id': meeting_id })
    all_events = []
    for user in meeting['users']:
        all_events.extend(user['events'])
    return all_events

def get_meeting_range(meeting_id):
    """
    Return a representation of the time constraints set by the creator of the meeting.

    Looks like: { 'begin_date': <datetime_iso_string>, 'end_date': <datetime_iso_string>,
                  'begin_time': <datetime_iso_string>, 'end_time': <datetime_iso_string> }
    That is, the beginning of the date range at the start of the time range to the end of
    the date range at the end of the time range.
    """
    global collection
    meeting = collection.find_one({ '_id': meeting_id })
    return meeting['meeting_range']
