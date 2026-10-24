FROM python:3.12
WORKDIR /app
COPY . /app
COPY config.env /app/config.env
RUN pip install -r requirements.txt
CMD ["python", "main.py"]
