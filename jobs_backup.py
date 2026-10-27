import feedparser
import os
import requests
import json
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from urllib.parse import urljoin


load_dotenv()

BOT_TOKEN=os.getenv("BOT_TOKEN")
CHAT_ID=os.getenv("CHAT_ID")


with open("sent_jobs.json","r") as file:

    sent_jobs=json.load(file)


def send_telegram(message):

    url=f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"

    data={
        "chat_id":CHAT_ID,
        "text":message
    }

    try:

        response=requests.post(
            url,
            data=data,
            timeout=15
        )

        result=response.json()

        print("Telegram:",result)

        if result.get("ok"):

            return True

        return False

    except Exception as msg:

        print("Telegram error:",msg)

        return False


def get_application_link(job_url):

    try:

        response=requests.get(
            job_url,
            timeout=10,
            headers={
                "User-Agent":"Mozilla/5.0"
            }
        )

        soup=BeautifulSoup(response.text,"html.parser")

        links=soup.find_all("a",href=True)


        for link in links:

            href=link["href"]

            text=link.get_text(" ",strip=True).lower()

            full_url=urljoin(job_url,href)


            if "weworkremotely.com/job-seekers" in full_url:

                continue


            if "remoteok.com" in full_url:

                continue


            if "apply" in text or "application" in text:

                if full_url.startswith("http"):

                    return full_url


        for link in links:

            href=link["href"]

            full_url=urljoin(job_url,href)


            if "weworkremotely.com" not in full_url and "remoteok.com" not in full_url:

                if full_url.startswith("http"):

                    return full_url


        return job_url


    except Exception as msg:

        print("Application link error:",msg)

        return job_url


def get_remote_ok_jobs():

    try:

        url="https://remoteok.com/api"

        response=requests.get(
            url,
            timeout=15,
            headers={
                "User-Agent":"Mozilla/5.0"
            }
        )

        data=response.json()

        jobs=[]


        for job in data:

            if not isinstance(job,dict):

                continue


            if "position" not in job:

                continue


            title=job.get("position","")

            description=job.get("description","")

            job_link=job.get("url","")


            jobs.append({
                "title":title,
                "summary":description,
                "link":job_link
            })


        return jobs


    except Exception as msg:

        print("Remote OK error:",msg)

        return []


job_sources = [

    {
        "name":"We Work Remotely",
        "type":"rss",
        "url":"https://weworkremotely.com/categories/remote-programming-jobs.rss"
    },

    {
        "name":"Remote OK",
        "type":"api",
        "url":"https://remoteok.com/api"
    }

]


ai_title_keywords = [

    "ai engineer",
    "artificial intelligence engineer",
    "ml engineer",
    "machine learning engineer",
    "ai/ml engineer",
    "ai / ml engineer",
    "deep learning engineer",
    "nlp engineer",
    "natural language processing engineer",
    "computer vision engineer",
    "mlops engineer",
    "genai engineer",
    "generative ai engineer",
    "llm engineer",
    "ai researcher",
    "machine learning researcher",
    "ai trainer",
    "prompt engineer",
    "prompt engineering",
    "data scientist",
    "machine learning scientist",
    "ai scientist"

]


ai_technology_keywords = [

    "rag",
    "retrieval augmented generation",
    "agentic ai",
    "large language model",
    "llm",
    "generative ai",
    "genai",
    "machine learning",
    "deep learning",
    "pytorch",
    "tensorflow",
    "computer vision",
    "natural language processing"

]


entry_keywords = [

    "junior",
    "entry level",
    "entry-level",
    "fresher",
    "graduate",
    "new grad",
    "0-1 years",
    "0-2 years",
    "0–1 years",
    "0–2 years",
    "will train",
    "no experience",
    "no prior experience"

]


senior_keywords = [

    "senior",
    "lead",
    "principal",
    "staff",
    "director",
    "manager",
    "head of"

]


for source in job_sources:

    source_name=source["name"]

    source_url=source["url"]

    print("CHECKING:",source_name)


    if source["type"]=="rss":

        feed=feedparser.parse(source_url)

        jobs=feed.entries


    elif source["type"]=="api":

        jobs=get_remote_ok_jobs()


    print("Jobs found:",len(jobs))


    for job in jobs:

        title=job.get("title","").lower()

        description=job.get("summary","").lower()

        text=title+" "+description


        is_ai=False

        is_entry=False

        is_senior=False

        matched_keywords=[]


        # Check strong AI/ML job titles

        for keyword in ai_title_keywords:

            if keyword in title:

                is_ai=True

                matched_keywords.append(keyword)


        # Check AI technologies ONLY in the job title

        for keyword in ai_technology_keywords:

            if keyword in title:

                is_ai=True

                matched_keywords.append(keyword)


        # Check entry-level signals in title + description

        for keyword in entry_keywords:

            if keyword in text:

                is_entry=True

                break


        # Check senior signals ONLY in title

        for keyword in senior_keywords:

            if keyword in title:

                is_senior=True

                break


        if is_ai and not is_senior:

            job_title=job.get("title","")

            job_link=job.get("link","")


            if not job_link:

                continue


            if job_link in sent_jobs:

                print("ALREADY SENT - SKIPPING")

                print("Job:",job_title)

                print("--------------------")

                continue


            # Remove duplicate keywords

            matched_keywords=list(dict.fromkeys(matched_keywords))


            application_link=get_application_link(job_link)


            print("MATCH FOUND")

            print("Source:",source_name)

            print("Job:",job_title)

            print("AI/ML:",True)

            print("AI Keywords:",matched_keywords)

            print("Entry Level:",is_entry)

            print("Link:",job_link)

            print("Application Link:",application_link)

            print("--------------------")


            message=f"""🚀 NEW REMOTE AI/ML JOB

Source: {source_name}

Job:
{job_title}

🤖 AI/ML:
{", ".join(matched_keywords)}

🎯 Entry Level:
{"YES" if is_entry else "Not specified"}

🔗 Apply:
{application_link}
"""


            telegram_sent=send_telegram(message)


            if telegram_sent:

                sent_jobs.append(job_link)


                with open("sent_jobs.json","w") as file:

                    json.dump(sent_jobs,file,indent=4)

                print("SAVED TO sent_jobs.json")

            else:

                print("NOT SAVED - Telegram notification failed")

            print("--------------------")