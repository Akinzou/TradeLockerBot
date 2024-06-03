# TradeLockerBot  [![License: CC BY-NC-SA 4.0](https://img.shields.io/badge/License-CC_BY--NC--SA_4.0-lightgrey.svg)] ![Python package](https://github.com/Akinzou/TradeLocker/actions/workflows/python-package.yml/badge.svg) ![Docker Image: Build and Upload](https://github.com/Akinzou/TradeLocker/actions/workflows/docker-image.yml/badge.svg)
### Webhook TradingView Bot for Automated Position Management
TradeLocker is a webhook bot designed to seamlessly integrate with TradingView, enabling automated opening and closing of trading positions.

## Install

### Update Code

If you update the code, run the following command to delete the previous image:

```sh
docker rmi -f ghcr.io/akinzou/tradelocker_bot:latest
```

### Pull the Latest Image
Download the latest image using the command:

```sh
docker pull ghcr.io/akinzou/tradelocker_bot:latest
```

### Verify Download
Check if the image has been downloaded:

```sh
docker images
```
You should see:
```sh
ghcr.io/akinzou/tradelocker_bot   latest
```

### Run the Container
Run the container with the following command:
```sh
docker run -t -p 443:443 -e username=your_username -e password=your_password -e server=your_server -e env=demo/live --rm ghcr.io/akinzou/tradelocker_bot:latest
```
### Verification
After running the container, you should see green text indicating successful authentication:

<pre>
 _____              _      _               _             ____        _
|_   _| __ __ _  __| | ___| |    ___   ___| | _____ _ __| __ )  ___ | |_
  | || '__/ _` |/ _` |/ _ \ |   / _ \ / __| |/ / _ \ '__|  _ \ / _ \| __|
  | || | | (_| | (_| |  __/ |__| (_) | (__|   <  __/ |  | |_) | (_) | |_
  |_||_|  \__,_|\__,_|\___|_____\___/ \___|_|\_\___|_|  |____/ \___/ \__|
</pre>
```diff
+[INFO] tradelocker.tradelocker_api 2024-05-30 11:25:31,834 tradelocker_api _auth_with_password: 665 Successfully fetched authentication tokens
```




### Access the Webhook Bot
You can now access the webhook bot at:
```sh
http://localhost:443/strategy
```
or
```sh
http://yourIP:443/strategy
```
You should see the following message on the site:
```sh
{"detail":"Method Not Allowed"}
```

### Cahnge URL:
Run Container with addtional argument
```sh
-e url=/your_url
```

You can use also
```sh
-e url=generate
```
For generate random URL



## Adding webhook alert to your strategy:
Use this format

```ssh
XAUUSD
{{strategy.order.action}}
0.01
500
1000
{{strategy.order.alert_message}}
```
where
```ssh
XAUUSD -> name of tradable instrument
{{strategy.order.action}} -> "buy"/"sell"
0.01 -> lot
500 -> take profit (offset mode)
1000 -> stop loss (offset mode)
{{strategy.order.alert_message}} -> "Open" for opening a position and closing the previous one, "Close" for only closing a position on the specific instrument
```

## Remember 
Remember to configure Nginx or another appropriate software to enable access to HTTPS. You will be able to use, for example

```sh
https://localhost/strategy
```

## Note:
This program is provided "as is" without any warranty. Use it at your own risk.
Before using this program in a live trading environment, thoroughly test it on a demo account to ensure its correctness and reliability.
