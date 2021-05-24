#!/usr/bin/env python3

import re, io, subprocess, threading, queue, shutil, time

class Fake:
    def start(self):
        self.run()

    def join(self):
        pass

class FFMPEGError(Exception):
    def __init__(self, exitcode, stderr):
        self.exitcode = exitcode
        self.stderr = stderr

        super().__init__()

    def __str__(self):
        return self.stderr.decode("ascii", "ignore")
    

_ffmpeg_executable = shutil.which("ffmpeg")
if _ffmpeg_executable is None:
    raise OSError("Can’t locate ffmpeg")

class ffmpegThread(threading.Thread):
    duration_re = re.compile(r"Duration: ([0-9:\.]+),")
    ffmpeg_executable = _ffmpeg_executable    
    
    def __init__(self, parameters, progress_f=None, info_f=None):
        """
        `parameters` list with everything that goes after “ffmpeg”.
        `progress_f` callable accepting a float 0 <= f <= 1, called
            with ffmpeg progress information.
        `info_f` callable accepting a dict that contains the data
            provided by ffpmeg -progress as key/value pairs plus
            a key `done` providing the float calculated for `progress_f`
            above.
        """
        self.parameters = parameters
        self.progress_f = progress_f
        self.info_f = info_f
        self._input_duration = None

        super().__init__()

        
    def indicate_progress(self, done, info):
        if self.progress_f is not None:
            self.progress_f(done)
            
        if self.info_f is not None:
            self.info_f(info)

    @property
    def input_duration(self):
        if self._input_duration is None:
            if self.ffmpeg is None:
                raise IOError("ffmpeg never got as far as "
                              "reading the duration.")
            while True:
                if not self.ffmpeg.stderr.readable():
                    time.sleep(.1)
                else:
                    line = self.ffmpeg.stderr.readline()
                    line = line.decode("ascii", "ignore")
                    match = self.duration_re.search(line)
                    if match is not None:
                        duration_s, = match.groups()
                        time, partial = duration_s.split(".")
                        partial = float("0." + partial)
                        hours, minutes, seconds = time.split(":")
                        self._input_duration = (float(hours) * 3600 +
                                                float(minutes) * 60 +
                                                float(seconds) + partial)
                        return self._input_duration
        else:
            return self._input_duration
            
    def process_info(self, info):
        # out_time_ms is in microseconds not ms
        out_time_ms = float(info["out_time_ms"])
        if out_time_ms > 0:
            out_time = out_time_ms / 1000000
            info["done"] = out_time / self.input_duration
            self.indicate_progress(info["done"], info)
        
    
    def run(self):
        cmd = [self.ffmpeg_executable, "-progress", "-"] + self.parameters
        self.ffmpeg = subprocess.Popen( cmd,
                                        stdin=subprocess.DEVNULL,
                                        stdout=subprocess.PIPE,
                                        stderr=subprocess.PIPE)

        info = {}
        while self.ffmpeg.stdout.readable():            
            line = self.ffmpeg.stdout.readline().strip()
            if line:
                line = line.decode("ascii", "ignore")
                key, value = line.split("=", 1)
                info[key] = value
                if key == "progress":
                    self.process_info(info)
                    info = {}
            else:
                break


        self.exitcode = self.ffmpeg.poll()
        self.stderr = self.ffmpeg.stderr.read()
        self.ffmpeg = None

    @property
    def exception(self):
        if not hasattr(self, "exitcode"):
            raise IOError("ffmpeg didn’t finish(, yet).")
        
        if self.exitcode:
            return FFMPEGError(self.exitcode, self.stderr)
        else:
            return None
        
if __name__ == "__main__":
    import sys

    if len(sys.argv) == 1:
        print("Usage: %s <ffmpeg-args>\n"
              "Will start ffmpeg with all those args, but display only "
              "progress percentage to stdout.", file=sys.stderr)
        sys.exit(-1)
    else:
        q = queue.Queue()

        def queue_info(info):
            q.put(info)

        def print_info():
            while True:
                info = q.get()
                amount = info["done"]
                if info["progress"] == "end":
                    # This is how ffmpeg infidicates completition.
                    return
                else:
                    print("              \r%i" % (int(amount * 100.0)), end="")
                    time.sleep(.1)

        print_info_thread = threading.Thread(target=print_info)
            
        print_info_thread.start()
        
        try:            
            ffmpeg_thread = ffmpegThread(sys.argv[1:], info_f=queue_info)
            ffmpeg_thread.start()
        except FFMPEGError as e:
            print(e.stderr)
            raise

        ffmpeg_thread.join()
        print_info_thread.join()
        
