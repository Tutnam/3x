#!/bin/bash
LOG="/tmp/bot-startup.log"
echo "$(date): START user=$(whoami) pwd=$(pwd)" >> $LOG

cd /root/3x/ || { echo "$(date): cd FAIL" >> $LOG; exit 1; }
echo "$(date): in $(pwd)" >> $LOG

test -f /root/3x/.venv/bin/activate || { echo "$(date): NO .venv" >> $LOG; exit 1; }
source /root/3x/.venv/bin/activate || { echo "$(date): venv FAIL" >> $LOG; exit 1; }
echo "$(date): venv OK python=$(which python)" >> $LOG

cd /root/3x/ && /usr/bin/screen -dmS mybot python src/app.py
if [ $? -eq 0 ]; then
    echo "$(date): screen SUCCESS" >> $LOG
else
    echo "$(date): screen FAIL" >> $LOG
fi

