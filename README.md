# TradeLocker
Webhook Bot

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
<p style="color:green;">To jest zielony tekst</p>
