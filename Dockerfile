FROM python:3.13-alpine

RUN apk add --no-cache su-exec \
 && adduser -D user

WORKDIR /opt/rdgen-seed
COPY . .
RUN chown -R user:user /opt/rdgen-seed \
 && su-exec user pip install --user --no-cache-dir -r requirements.txt

COPY docker-entrypoint.sh /usr/local/bin/rdgen-entrypoint
COPY rdgen-env-exec.py /usr/local/bin/rdgen-env-exec
RUN sed -i 's/\r$//' /usr/local/bin/rdgen-entrypoint /usr/local/bin/rdgen-env-exec \
 && chmod 755 /usr/local/bin/rdgen-entrypoint /usr/local/bin/rdgen-env-exec

ENV PYTHONUNBUFFERED=1

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --retries=3 CMD wget --spider http://127.0.0.1:8000

ENTRYPOINT ["/usr/local/bin/rdgen-entrypoint"]
CMD ["sh", "-c", "python manage.py migrate && exec /home/user/.local/bin/gunicorn --reload -c gunicorn.conf.py rdgen.wsgi:application"]
