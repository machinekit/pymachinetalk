# coding=utf-8
import ftplib
import os
import threading
from six.moves.urllib.parse import urlparse

from ..common import ComponentBase
from ..dns_sd import ServiceContainer, Service


class ApplicationFile(ComponentBase, ServiceContainer):
    def __init__(self, debug=True):
        self._error_string = ''
        self.on_error_string_changed = []
        ComponentBase.__init__(self)
        ServiceContainer.__init__(self)
        self.debug = debug
        self.state_condition = threading.Condition(threading.Lock())
        self.file_list_lock = threading.Lock()

        self.file_uri = ''
        self.local_file_path = ''
        self.remote_file_path = ''
        self.local_path = ''
        self.remote_path = ''
        self.transfer_state = 'NoTransfer'
        self.bytes_sent = 0.0
        self.bytes_total = 0.0
        self.progress = 0.0
        self.file = None

        self._file_list = []

        self._file_service = Service(type_='file')
        self.add_service(self._file_service)
        self.on_services_ready_changed.append(self._on_services_ready_changed)

    def _on_services_ready_changed(self, ready):
        self.file_uri = self._file_service.uri
        self.ready = ready

    @property
    def error_string(self):
        return self._error_string

    @error_string.setter
    def error_string(self, string):
        if self._error_string is string:
            return
        self._error_string = string
        for cb in self.on_error_string_changed:
            cb(string)

    @property
    def file_list(self):
        with self.file_list_lock:
            return self._file_list

    def _upload_worker(self):
        o = urlparse(self.file_uri)
        # test o.scheme

        filename = os.path.basename(self.local_file_path)
        self.remote_file_path = os.path.join(self.remote_path, filename)

        self._update_state('UploadRunning')  # lets start the upload
        if self.debug:
            print('[file] starting upload of %s' % filename)

        try:
            self.bytes_sent = 0.0
            self.bytes_total = os.path.getsize(self.local_file_path)
            f = open(self.local_file_path, 'r')
        except OSError as e:
            self._update_state('Error')
            self._update_error('file', str(e))
            return

        try:
            self.progress = 0.0
            ftp = ftplib.FTP()
            ftp.connect(host=o.hostname, port=o.port)
            ftp.login()
            ftp.storbinary(
                'STOR %s' % filename,
                f,
                blocksize=8192,
                callback=self._progress_callback,
            )
            ftp.close()
            f.close()
        except Exception as e:
            self._update_state('Error')
            self._update_error('ftp', str(e))
            return

        self._update_state('NoTransfer')  # upload successfully finished
        if self.debug:
            print('[file] upload of %s finished' % filename)

    def _download_worker(self):
        o = urlparse(self.file_uri)
        # test o.scheme

        filename = self.remote_file_path[len(self.remote_path) :]  # mid
        self.local_file_path = os.path.join(self.local_path, filename)

        self._update_state('DownloadRunning')  # lets start the upload
        if self.debug:
            print('[file] starting download of %s' % filename)

        try:
            local_path = os.path.dirname(os.path.abspath(self.local_file_path))
            if not os.path.exists(local_path):
                os.makedirs(local_path)
            self.file = open(self.local_file_path, 'w')
        except Exception as e:
            self._update_state('Error')
            self._update_error('file', str(e))
            return

        try:
            ftp = ftplib.FTP()
            ftp.connect(host=o.hostname, port=o.port)
            ftp.login()
            ftp.sendcmd("TYPE i")  # Switch to Binary mode
            self.progress = 0.0
            self.bytes_sent = 0.0
            self.bytes_total = ftp.size(filename)
            ftp.retrbinary('RETR %s' % filename, self._progress_callback)
            ftp.close()
            self.file.close()
            self.file = None
        except Exception as e:
            self._update_state('Error')
            self._update_error('ftp', str(e))
            return

        self._update_state('NoTransfer')  # upload successfully finished
        if self.debug:
            print('[file] download of %s finished' % filename)

    def _refresh_files_worker(self):
        o = urlparse(self.file_uri)
        # test o.scheme

        self._update_state('RefreshRunning')  # lets start the upload
        if self.debug:
            print('[file] starting file list refresh')

        try:
            ftp = ftplib.FTP()
            ftp.connect(host=o.hostname, port=o.port)
            ftp.login()
            with self.file_list_lock:
                self._file_list = ftp.nlst()
            ftp.close()
        except Exception as e:
            self._update_state('Error')
            self._update_error('ftp', str(e))
            return

        self._update_state('NoTransfer')  # upload successfully finished
        if self.debug:
            print('[file] file refresh finished')

    def _remove_file_worker(self, filename):
        o = urlparse(self.file_uri)
        # test o.scheme

        self._update_state('RemoveRunning')  # lets start the upload
        if self.debug:
            print('[file] removing %s' % filename)

        try:
            ftp = ftplib.FTP()
            ftp.connect(host=o.hostname, port=o.port)
            ftp.login()
            ftp.delete(filename)
            ftp.close()
        except Exception as e:
            self._update_state('Error')
            self._update_error('ftp', str(e))
            return

        self._update_state('NoTransfer')  # upload successfully finished
        if self.debug:
            print('[file] removing %s completed' % filename)

    def _progress_callback(self, data):
        if self.file is not None:
            self.file.write(data)
        self.bytes_sent += 8192
        self.progress = self.bytes_sent / self.bytes_total

    def start_upload(self):
        with self.state_condition:
            if not self.ready or self.transfer_state != 'NoTransfer':
                return

        thread = threading.Thread(target=self._upload_worker)
        thread.start()

    def start_download(self):
        with self.state_condition:
            if not self.ready or self.transfer_state != 'NoTransfer':
                return

        thread = threading.Thread(target=self._download_worker)
        thread.start()

    def refresh_files(self):
        with self.state_condition:
            if not self.ready or self.transfer_state != 'NoTransfer':
                return

        thread = threading.Thread(target=self._refresh_files_worker)
        thread.start()

    def remove_file(self, name):
        with self.state_condition:
            if not self.ready or self.transfer_state != 'NoTransfer':
                return

        thread = threading.Thread(target=self._remove_file_worker, args=(name,))
        thread.start()

    def abort(self):
        raise NotImplementedError('not implemented')

    def wait_completed(self, timeout=None):
        with self.state_condition:
            if self.transfer_state == 'NoTransfer':
                return True
            if self.transfer_state == 'Error':
                return False
            self.state_condition.wait(timeout=timeout)
            return self.transfer_state == 'NoTransfer'

    def _update_state(self, state):
        with self.state_condition:
            if self.transfer_state != state:
                self.transfer_state = state
                self.state_condition.notify()

    def _update_error(self, error, description):
        self.error_string = '[file] error: %s %s' % (error, description)

    def clear_error(self):
        self.error_string = ''

    def start(self):
        pass

    def stop(self):
        pass
