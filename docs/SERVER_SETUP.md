# Server Setup Guide

## Prerequisites
- Java 17+ (Paper 1.20.4)
- Node.js 18+
- Python 3.10+

## Steps
1. Install Java 17: https://adoptium.net/
2. Download Paper 1.20.4 from https://papermc.io/
3. Start server: java -Xmx2G -jar paper.jar nogui
4. Accept EULA: set eula=true in eula.txt
5. Set online-mode=false in server.properties
6. npm install
7. node src/bot/bot_server.js
8. python -m singularity.main --goal "Gather 3 oak logs"
