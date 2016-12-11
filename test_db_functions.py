"""
Nose tests for db_functions.py
"""

import db_functions as db
import flask_main, uuid, arrow

meeting_id = 'test-meeting'
user_ids = [ 'test-user1', 'test-user2' ]
event_ids = [ 'user1event1', 'user1event2', 'user2event1', 'user2event2' ]
meeting_range = {
    'begin_date': 'begin_date',
    'end_date': 'end_date',
    'begin_time': 'begin_time',
    'end_time': 'end_time'
}

empty_test_meeting = {
  '_id': 'test-meeting',
  'created': 'creation-date',
  'meeting_range': {
    'begin_date': 'begin_date',
    'end_date': 'end_date',
    'begin_time': 'begin_time',
    'end_time': 'end_time'
  },
  'users': []
}

full_test_meeting = {
  '_id': 'test-meeting',
  'created': 'creation-date',
  'meeting_range': {
    'begin_date': 'begin_date',
    'end_date': 'end_date',
    'begin_time': 'begin_time',
    'end_time': 'end_time'
  },
  'users': [
    {
      'user_id': 'test-user1',
      'events': [
        {
          'event_id': 'user1event1',
          'summary': 'test-user1 first test event',
          'start': 'start datetime',
          'end': 'end datetime'
        },
        {
          'event_id': 'user1event2',
          'summary': 'test-user1 second test event',
          'start': 'start datetime',
          'end': 'end datetime'
        },
      ]
    },
    {
      'user_id': 'test-user2',
      'events': [
        {
          'event_id': 'user2event1',
          'summary': 'test-user2 first test event',
          'start': 'start datetime',
          'end': 'end datetime'
        },
        {
          'event_id': 'user2event2',
          'summary': 'test-user2 second test event',
          'start': 'start datetime',
          'end': 'end datetime'
        },
      ]
    },
  ]
}

c = db.connect() # db collection

##
# helper functions
##
def clean():
    c.remove({ '_id': meeting_id })

def insert_full_meeting():
    clean()
    c.insert(full_test_meeting)

def insert_empty_meeting():
    clean()
    c.insert(empty_test_meeting)

##
# test functions
##
def test_create_meeting():
    clean()
    assert c.find({ '_id': meeting_id }).count() == 0
    db.create_meeting(meeting_id, meeting_range, 'title', 'desc', {'hours': 0, 'minutes': 1}, 'bob')
    assert c.find({ '_id': meeting_id }).count() == 1

def test_add_user_with_events():
    insert_empty_meeting()
    events = [{ 'event_id': event_ids[0], 'summary': 'test', 'start': 'datetime', 'end': 'datetime' },
              { 'event_id': event_ids[1], 'summary': 'testing', 'start': 'datetime', 'end': 'datetime' }]
    db.add_user_with_events(meeting_id, user_ids[0], events)
    assert c.find_one({ '_id': meeting_id })['users'][0]['events'] == events

def test_get_user_events():
    insert_full_meeting()
    events = [
        {
          'event_id': 'user1event1',
          'summary': 'test-user1 first test event',
          'start': 'start datetime',
          'end': 'end datetime'
        },
        {
          'event_id': 'user1event2',
          'summary': 'test-user1 second test event',
          'start': 'start datetime',
          'end': 'end datetime'
        },
    ]
    assert db.get_user_events(meeting_id, user_ids[0]) == events

def test_get_all_events():
    insert_full_meeting()
    events = [
        {
          'event_id': 'user1event1',
          'summary': 'test-user1 first test event',
          'start': 'start datetime',
          'end': 'end datetime'
        },
        {
          'event_id': 'user1event2',
          'summary': 'test-user1 second test event',
          'start': 'start datetime',
          'end': 'end datetime'
        },
        {
          'event_id': 'user2event1',
          'summary': 'test-user2 first test event',
          'start': 'start datetime',
          'end': 'end datetime'
        },
        {
          'event_id': 'user2event2',
          'summary': 'test-user2 second test event',
          'start': 'start datetime',
          'end': 'end datetime'
        }
    ]
    assert db.get_all_events(meeting_id) == events

def test_get_meeting_range():
    insert_empty_meeting()
    assert db.get_meeting_range(meeting_id) == meeting_range

def test_remove_event():
    insert_full_meeting()
    events = [
        {
          'event_id': 'user1event1',
          'summary': 'test-user1 first test event',
          'start': 'start datetime',
          'end': 'end datetime'
        },
        {
          'event_id': 'user1event2',
          'summary': 'test-user1 second test event',
          'start': 'start datetime',
          'end': 'end datetime'
        },
    ]
    assert db.get_user_events(meeting_id, user_ids[0]) == events
    db.remove_event(meeting_id, user_ids[0], 'user1event1')
    assert db.get_user_events(meeting_id, user_ids[0]) == events[1:]
