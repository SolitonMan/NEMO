FROM python:3.6

# Install LDAP support
ARG DEBIAN_FRONTEND=noninteractive
RUN apt-get update --fix-missing
RUN apt-get -y upgrade
RUN apt-get install -y libsasl2-dev libldap2-dev
RUN apt-get install -y slapd ldap-utils
RUN pip install python-ldap
RUN pip install django-auth-ldap

# Install PostgreSQL support
RUN pip install psycopg2-binary

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
#RUN pip install django-developer-panel

# Intall NEMO (in the current directory) and Gunicorn
COPY . /nemo/
RUN pip install /nemo/ gunicorn==20.0.4
RUN rm --recursive --force /nemo/

RUN mkdir /nemo
WORKDIR /nemo
ENV DJANGO_SETTINGS_MODULE "settings"
ENV PYTHONPATH "/nemo/"
COPY gunicorn_configuration.py /etc/

EXPOSE 8000/tcp

COPY start_NEMO_in_Docker.sh /usr/local/bin/
RUN chmod +x /usr/local/bin/start_NEMO_in_Docker.sh
CMD ["start_NEMO_in_Docker.sh"]
