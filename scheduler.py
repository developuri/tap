from apscheduler.schedulers.background import BackgroundScheduler
from tistory import post_to_tistory
from datetime import datetime

scheduler = BackgroundScheduler()
scheduler.start()

def schedule_post(blog_url, title, content, run_time):
    def job():
        post_to_tistory("default", blog_url, title, content)

    scheduler.add_job(job, 'date', run_date=run_time) 