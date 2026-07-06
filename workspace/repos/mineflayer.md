# Repo Card: Mineflayer

**URL**: https://github.com/PrismarineJS/mineflayer
**License**: MIT
**Language**: JavaScript (Node.js)
**MC Version**: 1.8 - 1.21
**Activity**: Very Active (11k+ stars, frequent updates)
**Description**: Full-featured Minecraft bot framework for creating bots that can move, dig, place, craft, attack, trade, and more.
**Key APIs**:
  - Bot creation and connection
  - Player state (position, health, food, XP)
  - Inventory management
  - Block interaction (dig, place)
  - Entity tracking and interaction
  - Crafting system
  - Chat system
  - Event system (chat, entitySpawn, playerJoin, etc.)
**Plugin Ecosystem**:
  - mineflayer-pathfinder: A* navigation
  - mineflayer-pvp: Combat
  - mineflayer-collectblock: Auto-collect
  - mineflayer-auto-eat: Auto food management
  - prismarine-viewer: Web-based debug viewer
**Dependencies**: prismarine-chunk, prismarine-world, prismarine-entity, minecraft-data
**Install Difficulty**: Easy (npm install)
**Reproducibility**: High
**Reusable Modules**: Everything — this is our primary bot interface
**Risks**:
  - Node.js only (need Python bridge)
  - Some features lag behind Minecraft updates
  - Complex actions may need custom plugin code
**Value to Project**: Core dependency. Our entire action system is built on Mineflayer.
**Integration Plan**: Use via TCP socket bridge (bot_server.js)
