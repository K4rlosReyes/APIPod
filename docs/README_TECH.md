
# Queue mixin, Job Queue and Job lifecycle

The fastapi router backend uses the _queue_mixin to manage jobs.
Every call to an task_endpoint will submit the job via the mixin to the job_queue.


Jobs are managed by the job_queue.
When a job is created in, it goes through a series of stages before it is completed. 

The stages are:
- validate_job_before_add: Used to validate parameters, user permissions, etc.
- add_job: job gets added to job store.
- create_job: literally creates the job. Can be overridden to use a specialized job class.
- process_job: The main job processing function. This is where the actual work is done.
- complete_job: Called when the job is completed. This is where the job is marked as completed and the result is stored.
- remove_job: 
  - Called when the job is removed from the JobStore and RAM. 
  - This happens when the user gets the result of the job or when the job was never collected (orphant job). 

