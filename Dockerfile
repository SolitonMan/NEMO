FROM python:3.11

# Install LDAP support
ARG DEBIAN_FRONTEND=noninteractive
RUN apt-get update --fix-missing
RUN apt-get -y upgrade
RUN apt-get install -y memcached telnet

RUN pip install --upgrade pip

# memcached seems to be needed for the microsoft auth or other supporting software
RUN pip install python-memcached

# include pytz
RUN pip install pytz

# Install django_microsoft_auth
RUN pip install django_microsoft_auth

# Install PostgreSQL support
#RUN pip install psycopg2-binary
RUN pip install "psycopg[binary]"

# Install easyaudit from https://github.com/soynatan/django-easy-audit
RUN pip install django-easy-audit

# Install schedule library for interlock pulsing
RUN pip install schedule

# Install xmltodict to support simple parsing
RUN pip install xmltodict

# Install DEBUG support
#RUN pip install django-debug-toolbar
#RUN pip install django-debug-toolbar-request-history
#RUN pip install django-debug-panel
RUN pip install django-developer-panel

# install replacement for Memcache
RUN pip install pymemcache
RUN pip install django-pymemcache 

# install bootstrap support
RUN pip install django-widget-tweaks

# Intall NEMO (in the current directory) and Gunicorn
COPY . /nemo/
#RUN pip install /nemo/ gunicorn==20.0.4
RUN pip install /nemo/ gunicorn
RUN rm --recursive --force /nemo/

RUN mkdir /nemo
WORKDIR /nemo
ENV DJANGO_SETTINGS_MODULE="settings"
ENV PYTHONPATH="/nemo/"
ENV OAUTHLIB_RELAX_TOKEN_SCOPE="true"
COPY gunicorn_configuration.py /etc/

EXPOSE 8000/tcp

COPY start_NEMO_in_Docker.sh /usr/local/bin/
RUN chmod +x /usr/local/bin/start_NEMO_in_Docker.sh
CMD ["start_NEMO_in_Docker.sh"]
