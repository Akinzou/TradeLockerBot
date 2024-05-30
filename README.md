# TradeLocker  ![Python package 3.11/3.12](https://github.com/Akinzou/TradeLocker/actions/workflows/python-package.yml/badge.svg) ![Docker Image: Build and Upload](https://github.com/Akinzou/TradeLocker/actions/workflows/docker-image.yml/badge.svg)
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
docker run -p 443:443 -e username=your_username -e password=your_password -e server=your_server -e env=demo/live --rm ghcr.io/akinzou/tradelocker_bot:latest
```
### Verification
After running the container, you should see green text indicating successful authentication:
```diff
+[INFO] tradelocker.tradelocker_api 2024-05-30 11:25:31,834 tradelocker_api _auth_with_password: 665 Successfully fetched authentication tokens
```

###Access the Webhook Bot
You can now access the webhook bot at:
```sh
http://localhost:443/
```
or
```sh
http://yourIP:443/
```
You should see the following message on the site:
```sh
{"detail":"Not Found"}
```

## Note:
This program is provided "as is" without any warranty. Use it at your own risk.
Before using this program in a live trading environment, thoroughly test it on a demo account to ensure its correctness and reliability.
