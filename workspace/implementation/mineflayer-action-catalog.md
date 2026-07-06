# Mineflayer Action Catalog

## Movement Actions
| Action | API | Params | Notes |
|--------|-----|--------|-------|
| move_to | bot.pathfinder.goto(new GoalNear(x,y,z,range)) | x,y,z,range | Uses A* pathfinding |
| look_at | bot.lookAt(Vec3) | x,y,z | Sets yaw/pitch |
| set_control | bot.setControlState(name,state) | forward/back/left/right/jump/sprint | Direct movement |
| stop | bot.pathfinder.stop() | none | Stop all movement |

## Block Actions
| Action | API | Params | Notes |
|--------|-----|--------|-------|
| dig | bot.dig(block) | x,y,z or blockRef | Need correct tool for block type |
| place | bot.placeBlock(refBlock,faceVec) | x,y,z,face | Need item in hand |
| activate_block | bot.activateBlock(block) | x,y,z | Open containers, flip levers |

## Inventory Actions
| Action | API | Params | Notes |
|--------|-----|--------|-------|
| equip | bot.equip(item,destination) | itemName,hand/off-hand/armor | Auto-finds item |
| craft | bot.craft(recipe,count,table) | recipeId,count,table | Need materials |
| toss | bot.toss(itemType,metadata,count) | itemName,count | Drop items |
| open_container | bot.openContainer(block) | x,y,z | Chest/furnace |

## Combat Actions
| Action | API | Params | Notes |
|--------|-----|--------|-------|
| attack | bot.attack(entity) | entityId | Melee attack |
| activate_item | bot.activateItem() | none | Use held item (bow, food) |
| deactivate_item | bot.deactivateItem() | none | Stop using item |

## Info Queries
| Query | API | Returns |
|-------|-----|---------|
| position | bot.entity.position | Vec3 |
| health | bot.health | float 0-20 |
| food | bot.food | int 0-20 |
| inventory | bot.inventory.items() | Item[] |
| entities | bot.entities | EntityMap |
| blockAt | bot.blockAt(pos) | Block |
| time | bot.time.timeOfDay | int 0-24000 |
| experience | bot.experience | {level, points} |
