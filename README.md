# TradeLockerBot  [![License: CC BY-NC-SA 4.0](https://img.shields.io/badge/License-CC_BY--NC--SA_4.0-lightgrey.svg)] [![Python package](https://github.com/Akinzou/TradeLocker/actions/workflows/python-package.yml/badge.svg) ![Docker Image: Build and Upload](https://github.com/Akinzou/TradeLocker/actions/workflows/docker-image.yml/badge.svg)]
### Webhook TradingView Bot for Automated Position Management
TradeLocker is a webhook bot designed to seamlessly integrate with TradingView, enabling automated opening and closing of trading positions.

## Install

### Update Code
$\color{red}{\textsf{Use only if you have already downloaded the image.}}$  
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
docker run -t -p 443:443 --name prod -e username='your_username' -e password='your_password' -e server='your_server' -e env=demo/live --rm ghcr.io/akinzou/tradelocker_bot:latest
```
The use of the --name prod option in the docker run command assigns the name prod to the running container. As a result, after executing the command, the container named prod will be visible in the output of the docker ps command.

Do not forget to select the environment as either demo or live. 
### Run a specific account
If you have more than one trading account under your main account, you can specify which one to use by:
```sh
-e acc_id = your_acc_id
```
or
```sh
-e acc_num = your_acc_number
```
### Change port
The
```sh 
-port
``` 
argument specifies the port on which the FastAPI application will run. By default, it is set to 443, but the user can provide a custom port.
** Example usage: **
```sh
python tradelocker_bot.py --port 8080
```
This will start the application on port 8080, making the webhook accessible at **http://localhost:8080/strategy** 

### Verification
After running the container, you should see green text indicating successful authentication:

```diff
 _____              _      _               _             ____        _   
|_   _| __ __ _  __| | ___| |    ___   ___| | _____ _ __| __ )  ___ | |_ 
  | || '__/ _` |/ _` |/ _ \ |   / _ \ / __| |/ / _ \ '__|  _ \ / _ \| __|
  | || | | (_| | (_| |  __/ |__| (_) | (__|   <  __/ |  | |_) | (_) | |_ 
  |_||_|  \__,_|\__,_|\___|_____\___/ \___|_|\_\___|_|  |____/ \___/ \__|

+[INFO] tradelocker.tradelocker_api 2024-05-30 11:25:31,834 tradelocker_api _auth_with_password: 665 Successfully fetched authentication tokens
```
Additionally, check on which account you are signed in; it will print the number and ID.

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
### $\color{lime}{\textsf{For safety reasons, generating a random URL for the strategy:}}$  
Use:
```sh
-e url=generate
```

and you should see:

```diff
                                  _
 ___  __ ___   _____   _   _ _ __| |
/ __|/ _` \ \ / / _ \ | | | | '__| |
\__ \ (_| |\ V /  __/ | |_| | |  | |
|___/\__,_| \_/ \___|  \__,_|_|  |_|

/yourgenerated/url
```
$\color{red}{\textsf{Save it, it is only shown once}}$  
This URL is for webhook execution in the trading environment.

## Adding webhook alert to your strategy:
Use this format

```ssh
XAUUSD
{{strategy.order.action}}
0.01/100
500
1000
{{strategy.order.alert_message}}
Invert
```
where:

- **XAUUSD**: Name of the tradable instrument.
- **{{strategy.order.action}}**: The action to perform, either `"buy"` or `"sell"`.
- **0.01/100**: Dynamic lot size. The format `<lot>/<divider>` calculates the lot size as `0.01` lots for every `100` units of balance.
- **500**: Take profit value in offset mode.
- **1000**: Stop loss value in offset mode.
- **{{strategy.order.alert_message}}**:
  - `"open"`: Opens a new position and closes any existing position on the same instrument.
  - `"close"`: Closes the current position on the specific instrument.
- **Invert**: If set to `Invert`, reverses the direction of the trade (`buy` becomes `sell`, and `sell` becomes `buy`).


### Dynamic Lot
Dynamic lot allows the position size to be calculated based on the available account balance.
```ssh
**Format: <lot>/<divider>**  
<lot>: The base lot size.  
<divider>: The balance divisor used for calculation.  
```
**How it works:**  
Sending the value 0.01/100 will instruct the bot to open 0.01 lot for every 100 units of the account balance.  
The position size is rounded to two decimal places.  
  
**Example calculation:**  
Balance: 1000  
Sent lot: 0.01/100  
  
**Calculation:**  
```
lot = (balance / divider) * base_lot
lot = (1000 / 100) * 0.01
lot = 0.1
The bot will open a position with a size of 0.1 lots.
```

### Invert
The Invert option allows reversing the trade direction:  
If the value is Invert, the bot will swap:  
buy to sell  
sell to buy  
If the value is NonInvert, the direction remains unchanged.   
  
**Example behavior:**  
Webhook direction: buy.  
isInvert value: Invert. 
  
**Result: The bot will reverse buy to sell and open the corresponding position.**  
  
**Use case:**  
This is useful for strategies that involve hedging or need to reverse trade directions as part of risk management.  
  
## Remember 
Remember to configure Nginx or another appropriate software to enable access to HTTPS. You will be able to use, for example

```sh
https://localhost/strategy
```

## Note:
This program is provided "as is" without any warranty. Use it at your own risk.
Before using this program in a live trading environment, thoroughly test it on a demo account to ensure its correctness and reliability.
