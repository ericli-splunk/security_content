from os import error
import sys
from time import sleep
import splunklib.client as client
import splunklib.results as results
import requests
import time
import timeit
import datetime
from typing import Union, Tuple
from modules.testing_service import TestResult
DEFAULT_EVENT_HOST = "ATTACK_DATA_HOST"
DEFAULT_DATA_INDEX = set(["main"])
FAILURE_SLEEP_INTERVAL_SECONDS = 60


def get_number_of_indexed_events(splunk_host, splunk_port, splunk_password, index:str, event_host:str=DEFAULT_EVENT_HOST, sourcetype:Union[str,None]=None )->int:

    try:
        service = client.connect(
            host=splunk_host,
            port=splunk_port,
            username='admin',
            password=splunk_password
        )
    except Exception as e:
        raise(Exception("Unable to connect to Splunk instance: " + str(e)))

    if sourcetype is not None:
        search = f'''search index="{index}" sourcetype="{sourcetype}" host="{event_host}" | stats count'''
    else:
        search = f'''search index="{index}" host="{event_host}" | stats count'''
    kwargs = {"exec_mode":"blocking"}
    try:
        job = service.jobs.create(search, **kwargs)
  
        #This returns the count in string form, not as an int. For example:
        #OrderedDict([('count', '59630')])
        results_stream = job.results(output_mode='json')
        count = None
        num_results = 0
        for res in results.JSONResultsReader(results_stream):
            num_results += 1
            if isinstance(res, dict) and 'count' in res:
                count = int(res['count'],10)
        if count is None:
            raise Exception(f"Expected the get_number_of_indexed_events search to only return 1 count, but got {num_results} instead.")
        
        return count    

    except Exception as e:
        raise Exception("Error trying to get the count while waiting for indexing to complete: %s"%(str(e)))
        
    


def wait_for_indexing_to_complete(splunk_host, splunk_port, splunk_password, sourcetype:str, index:str, check_interval_seconds:int=5)->bool:
    startTime = timeit.default_timer()
    previous_count = -1
    time.sleep(check_interval_seconds)
    while True:
        new_count = get_number_of_indexed_events(splunk_host, splunk_port, splunk_password, index=index, sourcetype=sourcetype)
        #print(f"Previous Count [{previous_count}] New Count [{new_count}]")
        if previous_count == -1:
            previous_count = new_count
        else:
            if new_count == previous_count:
                stopTime = timeit.default_timer()
                return True
            else:
                previous_count = new_count
        
        #If new_count is really low, then the server is taking some extra time to index the data.
        # So sleep for longer to make sure that we give time to complete (or at least process more
        # events so we don't return from this function prematurely) 
        if new_count < 2:
            time.sleep(check_interval_seconds*3)
        else:
            time.sleep(check_interval_seconds)
        



def test_detection_search(splunk_host:str, splunk_port:int, splunk_password:str, search:str, pass_condition:str, 
                          detection_name:str, earliest_time:str, latest_time:str, attempts_remaining:int=4, 
                          failure_sleep_interval_seconds:int=FAILURE_SLEEP_INTERVAL_SECONDS, FORCE_ALL_TIME=True)->TestResult:
    #Since this is an attempt, decrement the number of remaining attempts
    attempts_remaining -= 1
    
    #remove leading and trailing whitespace from the detection.
    #If we don't do this with leading whitespace, this can cause
    #an issue with the logic below - mainly prepending "|" in front
    # of searches that look like " | tstats <something>"
    if search != search.strip():
        print(f"The detection contained in {detection_name} contains leading or trailing whitespace.  Please update this search to remove that whitespace.")
        search = search.strip()
    
    if search.startswith('|'):
        updated_search = search
    else:
        updated_search = 'search ' + search 


    #Set the mode and timeframe, if required
    kwargs = {"exec_mode": "blocking"}
    if not FORCE_ALL_TIME:
        kwargs.update({"earliest_time": earliest_time,
                       "latest_time": latest_time})

    #Append the pass condition to the search
    splunk_search = f"{updated_search} {pass_condition}"

    try:
        service = client.connect(
            host=splunk_host,
            port=splunk_port,

            username='admin',
            password=splunk_password
        )
    except Exception as e:
        error_message = "Unable to connect to Splunk instance: %s"%(str(e))
        print(error_message,file=sys.stderr)
        return TestResult(generated_exception={"message":error_message})


    try:
        job = service.jobs.create(splunk_search, **kwargs)
        results_stream = job.results(output_mode='json')
        #Return all the content returned by the search
        return TestResult(no_exception=job.content)

    except Exception as e:
        error_message = "Unable to execute detection: %s"%(str(e))
        print(error_message,file=sys.stderr)
        return TestResult(generated_exception={"message":error_message})

    


def delete_attack_data(splunk_host:str, splunk_password:str, splunk_port:int, indices:set[str], host:str=DEFAULT_EVENT_HOST)->bool:
    
    
    try:
        service = client.connect(
            host=splunk_host,
            port=splunk_port,

            username='admin',
            password=splunk_password
        )
    except Exception as e:

        raise(Exception("Unable to connect to Splunk instance: " + str(e)))


    #print(f"Deleting data for {detection_filename}: {indices}")
    for index in indices:
        while (get_number_of_indexed_events(splunk_host, splunk_port, splunk_password, index=index, event_host=host) != 0) :
            splunk_search = f'search index="{index}" host="{host}" | delete'
            kwargs = {
                    "exec_mode": "blocking"}
            try:
                
                job = service.jobs.create(splunk_search, **kwargs)
                results_stream = job.results(output_mode='json')
                reader = results.JSONResultsReader(results_stream)


            except Exception as e:
                raise(Exception(f"Trouble deleting data using the search {splunk_search}: {str(e)}"))
        
    
    return True
