-- ==============================================================================
-- LUCIFER LUA v2.86 - AUTOMATED DONATION BOX DEPOSIT LISTENER (ENHANCED)
-- ==============================================================================
-- Script ini berjalan di executor Lucifer bot untuk mendeteksi deposit
-- World Lock, Diamond Lock, dan Blue Gem Lock via Donation Box in-game Growtopia.
-- Begitu lock masuk, bot akan langsung mengirimkan data ke Webhook Server Discord Store.
-- ==============================================================================

local CONFIG = {
    -- Nama world tempat bot stand-by menjaga donation box
    WORLD_NAME = "MEKAYAM",
    
    -- Door ID jika donation box berada di dalam pintu khusus (kosongkan jika tidak ada)
    DOOR_ID = "",

    -- URL Webhook Server Bot Discord
    API_URL = "https://discord.faru.web.id/gt-deposit",

    -- Token rahasia yang sama dengan GROWTOPIA_SECRET_TOKEN di file .env Discord Bot
    SECRET_TOKEN = "3212382761832",

    -- Apakah bot membalas via /msg privat in-game ke donatur setelah deposit diterima
    ENABLE_INGAME_MSG = true,

    -- (Opsional) Discord Webhook langsung untuk backup notifikasi ke channel Discord
    DISCORD_WEBHOOK_URL = "https://discord.com/api/webhooks/1552573711763120170/dN5tqH9OoQpynprLa3JHjbASqsh8v3MX-wbWYClmKGQuJP1mSEyI3WbDXHetbYzILoWN",

    -- Tampilkan seluruh teks chat yang masuk ke console Lucifer untuk kemudahan debugging
    DEBUG_MODE = true
}

-- Inisialisasi Bot
local bot = getBot()
if bot == nil then
    print("[ERROR] Script ini harus dijalankan di dalam konteks bot Lucifer!")
    return
end

print("==================================================")
print("  LUCIFER DONATION BOX AUTO-DEPOSIT v2.86 ACTIVE  ")
print("  Bot Name : " .. bot.name)
print("  Target   : World " .. CONFIG.WORLD_NAME)
print("  API URL  : " .. CONFIG.API_URL)
print("  Debug    : " .. tostring(CONFIG.DEBUG_MODE))
print("==================================================")

-- Aktifkan auto reconnect bawaan Lucifer
bot.auto_reconnect = true

-- Aktifkan console reader jika tersedia
pcall(function()
    local c = getConsole()
    if c then
        c.enabled = true
        print("[INIT] Console reader diaktifkan.")
    end
end)

-- Cache memori untuk mencegah double-trigger jika game mengirimkan pesan duplikat
local recent_cache = {}

-- Fungsi untuk membersihkan cache lama dan cek duplikasi
local function isDuplicate(growid, count, item_name)
    local now = os.time()
    local key = string.lower(growid) .. ":" .. count .. ":" .. string.lower(item_name)

    -- Hapus cache yang lebih dari 15 detik
    for k, timestamp in pairs(recent_cache) do
        if now - timestamp > 15 then
            recent_cache[k] = nil
        end
    end

    if recent_cache[key] and (now - recent_cache[key] <= 8) then
        return true
    end

    recent_cache[key] = now
    return false
end

-- Fungsi menentukan rate konversi lock ke World Lock (WL)
local function getItemRate(raw_item_name)
    local lower = string.lower(raw_item_name)
    if string.find(lower, "world lock") then
        return 1, "World Lock"
    elseif string.find(lower, "diamond lock") then
        return 100, "Diamond Lock"
    elseif string.find(lower, "blue gem lock") then
        return 10000, "Blue Gem Lock"
    end
    return 0, nil
end

-- Fungsi mem-parsing teks donasi dari berbagai format Growtopia
local function parseDonation(clean_text)
    -- Bersihkan karakter kurung siku dan tanda baca luar
    local text = string.gsub(clean_text, "[%[%]]", "")
    text = string.gsub(text, "^%s*(.-)%s*$", "%1")
    local lower = string.lower(text)

    -- Cek kata kunci donasi
    if not (string.find(lower, "donat") or string.find(lower, "place") or string.find(lower, "deposit")) then
        return nil, nil, nil
    end

    local growid, count_str, item_name = nil, nil, nil

    -- Format 1 (Standar Donation Box GT):
    -- "FaruuXes has donated 1 World Lock."
    -- "FaruuXes has donated 5 Diamond Locks."
    growid, count_str, item_name = string.match(text, "([%w_]+)%s+has%s+donated%s+(%d+)%s+(.-)%.?$")

    -- Format 2:
    -- "FaruuXes places 1 World Lock into the Donation Box"
    -- "FaruuXes places 1 World Lock into the Display Box"
    if not growid then
        growid, count_str, item_name = string.match(text, "([%w_]+)%s+places%s+(%d+)%s+(.-)%s+into")
    end

    -- Format 3:
    -- "FaruuXes deposited 1 World Lock into Donation Box"
    if not growid then
        growid, count_str, item_name = string.match(text, "([%w_]+)%s+deposited%s+(%d+)%s+(.-)%s+into")
    end

    -- Format 4 (Variasi bebas):
    if not growid then
        growid, count_str, item_name = string.match(text, "([%w_]+)%s+donated%s+(%d+)%s+(.-)%.?$")
    end

    if not growid then
        growid, count_str, item_name = string.match(text, "([%w_]+)%s+places%s+(%d+)%s+(.-)$")
    end

    if growid and count_str and item_name then
        local count = tonumber(count_str)
        -- Bersihkan nama item dari kurung (s), titik, atau spasi berlebih
        item_name = string.gsub(item_name, "%(s%)", "")
        item_name = string.gsub(item_name, "%.+$", "")
        item_name = string.gsub(item_name, "^%s*(.-)%s*$", "%1")

        return growid, count, item_name
    end

    return nil, nil, nil
end

-- Fungsi mengirim data deposit ke Webhook Server Bot Discord
local function notifyServer(growid, count, item_name, amount_wl)
    -- 1. Backup: Kirim notifikasi langsung via Discord Webhook jika ada
    if CONFIG.DISCORD_WEBHOOK_URL and CONFIG.DISCORD_WEBHOOK_URL ~= "" then
        pcall(function()
            local hook = Webhook.new(CONFIG.DISCORD_WEBHOOK_URL)
            hook.username = "Lucifer GT Deposit"
            hook.content = string.format("🎉 **Deposit Terdeteksi!**\n👤 GrowID: **`%s`**\n📦 Item: **%d %s** (+%d WL)\n🌍 World: **`%s`**", growid, count, item_name, amount_wl, CONFIG.WORLD_NAME)
            hook:send()
        end)
    end

    -- 2. Kirim ke Server Bot Discord API
    local client = HttpClient.new()
    client.url = CONFIG.API_URL
    client:setMethod(Method.post)
    client.headers["Content-Type"] = "application/json"
    client.headers["User-Agent"] = "Mozilla/5.0"
    client.headers["X-GT-Token"] = CONFIG.SECRET_TOKEN

    local payload = string.format(
        '{"growid":"%s","item_name":"%s","count":%d,"amount_wl":%d,"world":"%s"}',
        growid, item_name, count, amount_wl, CONFIG.WORLD_NAME
    )
    client.content = payload
    client.timeout = 8

    print("[HTTP] Mengirim deposit ke: " .. CONFIG.API_URL)
    local result = client:request()
    if result.error == 0 and result.status == 200 then
        print(string.format("[SUCCESS] Terverifikasi: %s mendepositkan %d %s (+%d WL)", growid, count, item_name, amount_wl))
        
        -- Cek apakah user unclaimed atau sukses
        if string.find(result.body or "", "unclaimed") then
            if CONFIG.ENABLE_INGAME_MSG then
                bot:say("/msg " .. growid .. " [STORE] GrowID kamu belum disetting di Discord! Ketik /setgrowid di bot Discord.")
            end
        else
            if CONFIG.ENABLE_INGAME_MSG then
                bot:say("/msg " .. growid .. " [STORE] Deposit " .. count .. "x " .. item_name .. " (+" .. amount_wl .. " WL) BERHASIL masuk!")
            end
        end
        return true
    else
        print(string.format("[ERROR] Gagal mengirim deposit ke server. Status: %s, Error: %s, Body: %s", tostring(result.status), tostring(result.error), tostring(result.body)))
        return false
    end
end

-- Handler utama saat ada teks/pesan dari server Growtopia
local function handleMessage(raw_message, source_tag)
    if not raw_message or raw_message == "" then
        return
    end

    local clean = removeColor(tostring(raw_message))
    local lower = string.lower(clean)

    -- Debug: Tampilkan pesan apapun yang masuk ke log Lucifer
    if CONFIG.DEBUG_MODE then
        -- Saring spam umum seperti ping/pong agar tidak terlalu bising
        if not string.find(lower, "ping") and not string.find(lower, "action|") then
            print(string.format("[DEBUG][%s] %s", source_tag or "IN", clean))
        end
    end

    -- Cek kata kunci donasi
    if string.find(lower, "donat") or string.find(lower, "places") or string.find(lower, "deposited") or string.find(lower, "donation box") then
        print("[MATCHING CANDIDATE] " .. clean)
        local growid, count, raw_item = parseDonation(clean)
        
        if growid and count and raw_item then
            local rate, valid_item_name = getItemRate(raw_item)
            if rate > 0 and valid_item_name then
                -- Cegah pemrosesan ganda
                if not isDuplicate(growid, count, valid_item_name) then
                    local total_wl = count * rate
                    print(string.format(">>> [DONATION DETECTED] %s -> %d %s (=%d WL) <<<", growid, count, valid_item_name, total_wl))
                    -- Jalankan pengiriman di background thread terpisah agar instan & tidak blocking
                    runThread(function(g_id, c_count, i_name, wl_amount)
                        notifyServer(g_id, c_count, i_name, wl_amount)
                    end, growid, count, valid_item_name, total_wl)
                else
                    print("[DUPLICATE] Pesan donasi diabaikan karena baru saja diproses.")
                end
            else
                print("[DONATION IGNORED] Item '" .. tostring(raw_item) .. "' bukan WL/DL/BGL.")
            end
        else
            print("[PARSE FAILED] Pola donasi tidak cocok dengan parser: " .. clean)
        end
    end
end

-- 1. Daftarkan event game_message
addEvent(Event.game_message, function(msg)
    handleMessage(msg, "game_message")
end)

-- 2. Daftarkan event generic_text
addEvent(Event.generic_text, function(text)
    handleMessage(text, "generic_text")
end)

-- 3. Daftarkan event variantlist (OnConsoleMessage & OnTalkBubble)
addEvent(Event.variantlist, function(varlist, net_id)
    pcall(function()
        local v0 = tostring(varlist[0] or "")
        local v1 = tostring(varlist[1] or "")
        local v2 = tostring(varlist[2] or "")
        local v3 = tostring(varlist[3] or "")

        if v0 == "OnConsoleMessage" then
            handleMessage(v1, "OnConsoleMessage")
        elseif v1 == "OnConsoleMessage" then
            handleMessage(v2, "OnConsoleMessage")
        elseif v0 == "OnTalkBubble" then
            handleMessage(v2, "OnTalkBubble")
        elseif v1 == "OnTalkBubble" then
            handleMessage(v3, "OnTalkBubble")
        end
    end)
end)

-- Callback saat script dihentikan
function on_stop(err)
    if err ~= "" and not string.find(string.lower(err), "exit_mode") then
        print("[LUCIFER STOPPED WITH ERROR] " .. err)
    else
        print("[LUCIFER STOPPED] Script dihentikan secara normal.")
    end
end

-- ==============================================================================
-- 1. WATCHDOG THREAD (World Keeper)
-- ==============================================================================
runThread(function()
    while true do
        sleep(3000)
        local b = getBot()
        if b and b.status == BotStatus.online then
            if not b:isInWorld(CONFIG.WORLD_NAME) then
                print("[WATCHDOG] Bot tidak berada di world " .. CONFIG.WORLD_NAME .. ". Melakukan warp...")
                if CONFIG.DOOR_ID ~= "" then
                    b:warp(CONFIG.WORLD_NAME, CONFIG.DOOR_ID)
                else
                    b:warp(CONFIG.WORLD_NAME)
                end
                sleep(4000)
            end
        end
    end
end)

-- ==============================================================================
-- 2. ACTIVE CONSOLE & HISTORY SCANNER
-- ==============================================================================
local last_scanned_console = ""
local scanned_history_set = {}

local function scanConsoleAndHistory()
    -- A. Pindai Console Log bawaan Lucifer
    pcall(function()
        local c = getConsole()
        if c and c.contents and c.contents ~= "" and c.contents ~= last_scanned_console then
            local new_text = c.contents
            last_scanned_console = new_text
            for line in string.gmatch(new_text, "[^\r\n]+") do
                local lower = string.lower(line)
                if string.find(lower, "donat") or string.find(lower, "places") or string.find(lower, "deposited") then
                    handleMessage(line, "ConsoleLog")
                end
            end
        end
    end)

    -- B. Pindai bot.history jika didukung
    pcall(function()
        local b = getBot()
        if b and b.history then
            for idx, hist_entry in ipairs(b.history) do
                local h_str = tostring(hist_entry)
                if not scanned_history_set[h_str] then
                    scanned_history_set[h_str] = true
                    local lower = string.lower(h_str)
                    if string.find(lower, "donat") or string.find(lower, "places") or string.find(lower, "deposited") then
                        handleMessage(h_str, "BotHistory")
                    end
                end
            end
        end
    end)
end

-- ==============================================================================
-- 3. MAIN LISTENER LOOP
-- ==============================================================================
if not bot:isInWorld(CONFIG.WORLD_NAME) then
    print("[INFO] Bot belum berada di world " .. CONFIG.WORLD_NAME .. ". Memulai warp...")
    if CONFIG.DOOR_ID ~= "" then
        bot:warp(CONFIG.WORLD_NAME, CONFIG.DOOR_ID)
    else
        bot:warp(CONFIG.WORLD_NAME)
    end
    sleep(4000)
end

print("[INFO] Bot siap! Mendengarkan donation box di world " .. CONFIG.WORLD_NAME .. "...")

-- Loop utama: kombinasikan pumping event dan pemindaian konsol aktif secara berkala
while true do
    pcall(function()
        listenEvents(500)
    end)

    scanConsoleAndHistory()

    sleep(100)
end




