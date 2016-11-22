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

def create_meeting(meeting_id):
    """
    Create new meeting object in database
    """
    global collection
    collection.insert({ '_id': meeting_id, 'created': arrow.now().isoformat(), 'users': [] })

def add_events(meeting_id, user_id, events):
    """
    Add an array of events to a meeting for a user
    """
    global collection
    collection.update({ '_id': meeting_id },
            { '$push': { 'users': { 'user_id': user_id, 'events': events } } } )

def remove_event(meeting_id, user_id, event_id):
    """
    Remove one event from a meeting for a user
    """
    global collection
    # TODO this isn't working
    collection.update({ '_id': meeting_id, 'users.user_id': user_id },
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

"""
Meeting document structure:

{
  _id: uuid,
  created: datetime,
  users: [
    {
      user_id: uuid,
      events: [
        {
          event_id: id (from gcal),
          summary: string,
          start: datetime,
          end: datetime
        },
        ...
      ]
    },
    ...
  ]
"""
