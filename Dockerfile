# Tradeskill portal - standard library only, so a slim Python image is all it needs.
FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 TZ=Asia/Kolkata HOST=0.0.0.0 PORT=8765
WORKDIR /app
COPY server.py longterm.py gtt.py kite.py nifty50.json nifty250.json ./
COPY static ./static
# data/ (settings, paper accounts, journal, Zerodha login, price cache) lives on the NAS volume
VOLUME /app/data
EXPOSE 8765
HEALTHCHECK --interval=2m --timeout=10s CMD python -c "import urllib.request,os;urllib.request.urlopen('http://127.0.0.1:%s/login' % os.environ['PORT'], timeout=8)"
CMD ["python", "server.py"]
