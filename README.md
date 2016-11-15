# proj6-Gcal
_Kory Schneider_

_CIS 322, Fall 2016_

## What is this?
This is a work-in-progress meeting coordinator that uses Google calendar to find common free times between users.

## Installation
Clone the repository:

    $ cd where/you/want/it
    $ git clone https://github.com/koryschneider/proj7-gcal meetme
    $ cd meetme

Then set it up and run it:

    $ bash ./configure && make service


## Usage
`$ make service` will start a Green Unicorn (gunicorn) server, which is more suitable for running over a long period of time.

`$ make run` will launch the server in debugging mode.

## Credit

Forked from Michal Young at https://github.com/UO-CIS-322/proj4-brevets for CIS 322: Intro to Software Engineering.
