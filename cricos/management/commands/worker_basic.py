
import os
from datetime import datetime
import time

from django.conf import settings
from django.core.management.base import BaseCommand

"""
Use this:

your_worker.py

from .worker_basic import BasicCommand as BaseCommand



class Command(BaseCommand):


    def handle(self, *args, **options):
        super(Command, self).handle(*args, **options)
        self.log('Starting')



        if self.codebase_changed():
            self.log("Codebase changed, exiting")
            self.nsq.io_loop.stop()

        self.log('Done')



"""

class BasicCommand(BaseCommand):

    def __init__(self, *args, **options):
        super(BasicCommand, self).__init__(*args, **options)
        self.codebase_changed()  # init

    def log(self, message, *args):

        if not hasattr(self, '_log_last'):
            self._log_last = time.time()

        msg = message
        if args:
            try:
                msg = message % args
            except Exception as ex:
                print("Error logging message, check it: message = %s, args = %s" % (repr(message), repr(args)))
                print(ex)

        if not hasattr(self, 'verbose'):
            print("self.verbose is not defined!. Please, add this code to the start of def handle() function to make log() working correct")
            print("")
            print("super(Command, self).handle(*args, **options)")
            print("")

        if getattr(self, 'verbose', False):
            print(u"%s (+%.6fs) %s" % (datetime.today().strftime(settings.DATETIME_FMT), time.time() - self._log_last, msg))

        self._log_last = time.time()

    def handle(self, *args, **options):
        self.verbose = int(options['verbosity']) > 1



    def codebase_changed(self):
        wsgi = os.path.join(settings.BASE_DIR, 'main', 'wsgi.py')

        mtime = int(os.stat(wsgi).st_mtime)

        if not hasattr(self, '_codebase_mtime'):
            self._codebase_mtime = mtime
            return False

        if self._codebase_mtime != mtime:
            # and forever return true on first occur
            #self.log("Codebase changed")
            return True
        else:
            return False

    def codebase_changed_hg(self):
        """Check .hgtags in project directory.

        somewhere in global loop:
        while not self.codebase_changed():
            do_job()

"""


        hgtags = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname( __file__)))), '.hgtags')

        mtime = int(os.stat(hgtags).st_mtime)

        if not hasattr(self, '_codebase_mtime'):
            self._codebase_mtime = mtime
            return False

        if self._codebase_mtime != mtime:
            # and forever return true on first occur
            #self.log("Codebase changed")
            return True
        else:
            return False
