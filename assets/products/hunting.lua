--config please dont change anything here ??
local MOVE_DELAY   = 600
local WRENCH_DELAY = 300
local JOIN_DELAY   = 2200
local MAIN_WORLD  = nil
local START_WORLD = nil
local pathMakerTileInfo = {}

local function saveStartWorld()
    local w = getWorld()
    if w then
        START_WORLD = w.name
    end
end

local function joinWorld(world)
    sendPacket(3,
        "action|join_request\n" ..
        "name|" .. world .. "\n" ..
        "invitedWorld|0"
    )
end

local function wrench(x, y)
    sendPacketRaw(false, {
        type   = 3,
        value  = 32,
        punchx = x,
        punchy = y,
        x      = getLocal().pos.x,
        y      = getLocal().pos.y
    })
end

local function scanSigns()
    local t = {}
    for _, tile in pairs(getTile() or {}) do
        if tile.fg == 20 then
            table.insert(t, {
                x = tile.pos.x,
                y = tile.pos.y
            })
        end
    end
    return t
end

local function scanPathMaker()
    pathMakerTileInfo = {}

    for _, tile in pairs(getTile() or {}) do
        if tile.fg == 1684 or tile.fg == 4482 then
            table.insert(pathMakerTileInfo, {
                x = tile.pos.x,
                y = tile.pos.y
            })
        end
    end
end

local function sendPMakerPacket()
    for _, t in ipairs(pathMakerTileInfo) do
        sendPacket(2,
            "action|dialog_return\n" ..
            "dialog_name|sign_edit\n" ..
            "tilex|"..t.x.."|\n" ..
            "tiley|"..t.y.."|\n" ..
            "sign_text|x0xburn"
        )
        sleep(120)
    end
end

local function autoWrenchSigns()
    local signs = scanSigns()

    for _, s in ipairs(signs) do
        findPath(s.x, s.y)
        sleep(MOVE_DELAY)

        wrench(s.x, s.y)
        sleep(WRENCH_DELAY)
    end
end

AddHook("OnTextPacket", "trig", function(type, pkt)
    if type ~= 2 or not pkt then return end
    if not pkt:find("action|input") then return end

    local text = pkt:match("text|([^\n]+)")
    if not text then return end

    local world = text:match("^/mainworld%s+(%S+)")
    if not world then return end

    MAIN_WORLD = world
    saveStartWorld()

    runThread(function()

        joinWorld(MAIN_WORLD)
        sleep(JOIN_DELAY)

        autoWrenchSigns()
        sleep(1000)

        if START_WORLD then
            joinWorld(START_WORLD)
            sleep(JOIN_DELAY)
        end

        scanPathMaker()
        sendPMakerPacket()
        sendPacket(3, "action|join_request\nname|"..START_WORLD.."|x0xburn|invitedWorld|0")

        logToConsole("`2AUTO FLOW DONE")
    end, "nihao")

    return true
end)
