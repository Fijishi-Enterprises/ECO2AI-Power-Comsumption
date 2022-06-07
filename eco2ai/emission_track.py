import os
import time
import platform
import pandas as pd
import requests
import numpy as np
from re import sub
import json
from pkg_resources import resource_stream
import sys
from apscheduler.schedulers.background import BackgroundScheduler

from eco2ai.tools.tools_gpu import *
from eco2ai.tools.tools_cpu import *

EMISSION_PER_MWT = 310.2
FROM_mWATTS_TO_kWATTH = 1000*1000*3600
FROM_kWATTH_TO_MWATTH = 1000


def set_params(**params):
    """
    Sets default Tracker attributes values:
    project_name = ...
    experiment_description = ...
    file_name = ...
    """
    dictionary = dict()
    filename = resource_stream('eco2ai', 'data/config.txt').name
    for param in params:
        dictionary[param] = params[param]
    # print(dictionary)
    if "project_name" not in dictionary:
        dictionary["project_name"] = "default project name"
    if "experiment_description" not in dictionary:
        dictionary["experiment_description"] = "default experiment description"
    if "file_name" not in dictionary:
        dictionary["file_name"] = "emission.csv"
    with open(filename, 'w') as json_file:
        json_file.write(json.dumps(dictionary))
    return dictionary


def get_params():
    """
    Returns default Tracker attributes values:
    project_name = ...
    experiment_description = ...
    file_name = ...
    """
    filename = resource_stream('eco2ai', 'data/config.txt').name
    if not os.path.isfile(filename):
        with open(filename, "w"):
            pass
    with open(filename, "r") as json_file:
        if os.path.getsize(filename):
            dictionary = json.loads(json_file.read())
        else:
            dictionary = {
                "project_name": "Deafult project name",
                "experiment_description": "no experiment description",
                "file_name": "emission.csv"
                }
    return dictionary


class Tracker:
    """
    This class calculates CO2 emissions during cpu or gpu calculations 
    In order to calculate gpu & cpu power consumption correctly you should create the 'Tracker' before any gpu or cpu usage
    For every new calculation create a new “Tracker.”

    ----------------------------------------------------------------------
    Use example:

    import eco2ai.Tracker
    tracker = eco2ai.Tracker()

    tracker.start()

    *your gpu calculations*
    
    tracker.stop()
    ----------------------------------------------------------------------
    """
    def __init__(self,
                 project_name=None,
                 experiment_description=None,
                 file_name=None,
                 measure_period=10,
                 emission_level=EMISSION_PER_MWT,
                 ):
        self._params_dict = get_params()
        self.project_name = project_name if project_name is not None else self._params_dict["project_name"]
        self.experiment_description = experiment_description if experiment_description is not None else self._params_dict["experiment_description"]
        self.file_name = file_name if file_name is not None else self._params_dict["file_name"]
        self.get_set_params(self.project_name, self.experiment_description, self.file_name)
        if (type(measure_period) == int or type(measure_period) == float) and measure_period <= 0:
            raise ValueError("measure_period should be positive number")
        self._measure_period = measure_period
        self._emission_level = emission_level
        self._scheduler = BackgroundScheduler(job_defaults={'max_instances': 4}, misfire_grace_time=None)
        self._start_time = None
        self._cpu = None
        self._gpu = None
        self._consumption = 0
        self._os = platform.system()
        if self._os == "Darwin":
            self._os = "MacOS"
        self._country = self.define_country()
        # self._mode == "first_time" means that CO2 emissions is written to .csv file first time
        # self._mode == "runtime" means that CO2 emissions is written to file periodically during runtime 
        # self._mode == "shut down" means that CO2 tracker is stopped
        self._mode = "first_time"
    
    def get_set_params(self, project_name, experiment_description, file_name):
        dictionary = dict()
        if project_name is not None:
            dictionary["project_name"] = project_name
        else: 
            dictionary["project_name"] = "default project name"
        if experiment_description is not None:
            dictionary["experiment_description"] = experiment_description
        else:
            dictionary["experiment_description"] = "default experiment description"
        if file_name is not None:
            dictionary["file_name"] = file_name
        else:
            dictionary["file_name"] = "emission.csv"
        set_params(**dictionary)

    def consumption(self):
        return self._consumption
    
    def emission_level(self):
        return self._emission_level
    
    def measure_period(self):
        return self._measure_period

    def _write_to_csv(self):
        # if user used older versions, it may be needed to upgrade his .csv file
        # but after all, such verification should be deleted
        # self.check_for_older_versions()
        duration = time.time() - self._start_time
        emissions = self._consumption * self._emission_level / FROM_kWATTH_TO_MWATTH
        if not os.path.isfile(self.file_name):
            with open(self.file_name, 'w') as file:
                file.write("project_name\texperiment_description(model type etc.)\tstart_time\tduration(s)\tpower_consumption(kWTh)\tCO2_emissions(kg)\tCPU_name\tGPU_name\tOS\tcountry\n")
                file.write(f"{self.project_name}\t{self.experiment_description}\t{time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(self._start_time))}\t{duration}\t{self._consumption}\t{emissions}\t{self._cpu.name()}/{self._cpu.tdp()} TDP: {self._cpu.cpu_num()} device(s)\t{self._gpu.name()} {self._gpu.gpu_num()} device(s)\t{self._os}\t{self._country}\n")
        else:
            with open(self.file_name, "a") as file:
                file.write(f"{self.project_name}\t{self.experiment_description}\t{time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(self._start_time))}\t{duration}\t{self._consumption}\t{emissions}\t{self._cpu.name()}/{self._cpu.tdp()} TDP: {self._cpu.cpu_num()} device(s)\t{self._gpu.name()} {self._gpu.gpu_num()} device(s)\t{self._os}\t{self._country}\n")
        if self._mode == "runtime":
            self._merge_CO2_emissions()
        self._mode = "runtime"


    # merges 2 CO2 emissions calculations together
    def _merge_CO2_emissions(self,):
        try:
            dataframe = pd.read_csv(self.file_name, sep='\t')
        except:
            dataframe = pd.read_csv(self.file_name)
        columns, values = dataframe.columns, dataframe.values
        row = values[-2]
        row[3:6] += values[-1][3:6]
        values = np.concatenate((values[:-2], row.reshape(1, -1)))
        pd.DataFrame(values, columns=columns).to_csv(self.file_name, index=False, sep='\t')


    # but after all, such verification should be deleted
    def check_for_older_versions(self,):
        # upgrades older emission.csv file up to new one
        if os.path.isfile(self.file_name):
            try:
                dataframe = pd.read_csv(self.file_name, sep='\t')
            except:
                dataframe = pd.read_csv(self.file_name)
            columns = "project_name,experiment_description,start_time,duration(s),power_consumption(kWTh),CO2_emissions(kg),CPU_name,GPU_name,OS,country".split(',')
            if list(dataframe.columns.values) != columns:
                dataframe = dataframe.assign(**{"CPU_name":"no cpu name", "GPU_name": "no gpu name","OS": "no os name", "country": "no country", "start_time": "no start time"})
                dataframe = pd.concat(
                    [
                    dataframe[["project_name", "experiment_description"]],
                    dataframe[["start_time"]],
                    dataframe[['time(s)', 
                                'power_consumption(kWTh)', 
                                'CO2_emissions(kg)',
                                'CPU_name',
                                'GPU_name',
                                'OS',
                                'country']],
                    ],
                    axis=1
                    )
                dataframe.columns = columns
                dataframe.to_csv(self.file_name, index=False, sep='\t', delimiter='\t')


    def _func_for_sched(self):
        cpu_consumption = self._cpu.calculate_consumption()
        if self._gpu.is_gpu_available:
            gpu_consumption = self._gpu.calculate_consumption()
        else:
            gpu_consumption = 0
        self._consumption += cpu_consumption
        self._consumption += gpu_consumption
        self._write_to_csv()
        self._consumption = 0
        self._start_time = time.time()
        if self._mode == "shut down":
            self._scheduler.remove_job("job")
            self._scheduler.shutdown()

    def start(self):
        self._cpu = CPU()
        self._gpu = GPU()
        self._start_time = time.time()
        self._scheduler.add_job(self._func_for_sched, "interval", seconds=self._measure_period, id="job")
        self._scheduler.start()
        # print(self._cpu.name())
        # print(self._gpu.name())

    def stop(self, ):
        if self._start_time is None:
            raise Exception("Need to first start the tracker by running tracker.start()")
        self._scheduler.remove_job("job")
        self._scheduler.shutdown()

        self._func_for_sched() 
        self._write_to_csv()
        self._mode = "shut down"

    def define_country(self,):
        region = sub(",", '',eval(requests.get("https://ipinfo.io/").content.decode('ascii'))['region'])
        country = sub(",", '',eval(requests.get("https://ipinfo.io/").content.decode('ascii'))['country'])
        return f"{region}/{country}"


def available_devices():
    '''
    Prints number of all available and seeable cpu & gpu devices
    '''
    all_available_cpu()
    all_available_gpu()
    # need to add RAM

def track(func):
    """
    decorator, that modifies function by creating Tracker object and 
    running Tracker.start() in the function beginning and 
    running Tracker.stop() in the end of function
    """
    def inner(*args):
        tracker = Tracker()
        tracker.start()
        # print(args)
        returned = func(*args)
        tracker.stop()
        del tracker
        return returned
    return inner