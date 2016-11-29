"""
Nose tests for db_functions.py
"""

import db_functions, flask_main, uuid, arrow

col = db_functions.connect() # db collection
meeting_id = 'test-meeting'
user_id = 'testuser'

def clean():
    col.remove({ '_id': meeting_id })

def test_create_meeting():
    clean()
    assert col.find({ '_id': meeting_id }).count() == 0
    db_functions.create_meeting(meeting_id, {'foo': 'bar'})
    assert col.find({ '_id': meeting_id }).count() == 1

def test_add_events():
    # don't clean()
    events = [{ 'event_id': 'abc', 'summary': 'test', 'start': 'datetime', 'end': 'datetime' },
              { 'event_id': 'cba', 'summary': 'testing', 'start': 'datetime', 'end': 'datetime' }]
    db_functions.add_events(meeting_id, user_id, events)
    assert dict(col.find_one({ '_id': meeting_id }))['users'][0]['events'] == events

def test_remove_event():
    clean()
    pass # TODO

def test_get_user_events():
    clean()
    pass # TODO

def test_get_all_events():
    clean()
    pass # TODO

def test_get_meeting_range():
    clean()
    meeting_range = { 'start': 'datetime1', 'end': 'datetime2' }
    db_functions.create_meeting(meeting_id, meeting_range)
    assert dict(col.find({ '_id': meeting_range }))['meeting_range'] == meeting_range