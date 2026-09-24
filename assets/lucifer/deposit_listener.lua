-- ==============================================================================
-- LUCIFER LUA v2.86 - AUTOMATED DONATION BOX DEPOSIT LISTENER
-- ==============================================================================
-- Script ini berjalan di client executor Lucifer bot untuk mendeteksi deposit
-- World Lock, Diamond Lock, dan Blue Gem Lock via Donation Box in-game Growtopia.
-- Begitu lock masuk, bot akan langsung mengirimkan data ke Webhook Server Discord Store.
-- ==============================================================================

local CONFIG = {
    -- Nama world tempat bot stand-by menjaga donation box
    WORLD_NAME = "STOREDEP",
    
    -- Door ID jika donation box berada di dalam pintu khusus (kosongkan jika tidak ada)
    DOOR_ID = "",

    -- URL Webhook Server Bot Discord (sesuaikan dengan domain / IP VPS kamu)
    -- Contoh: "http://127.0.0.1:8080/gt-deposit" atau "http://discord.faru.web.id:8080/gt-deposit"
    API_URL = "http://127.0.0.1:8080/gt-deposit",

    -- Token rahasia yang sama dengan GROWTOPIA_SECRET_TOKEN di file .env Discord Bot
    SECRET_TOKEN = "lucifer-secret-token-change-me",

    -- Apakah bot membalas via /msg privat in-game ke donatur setelah deposit diterima
    ENABLE_INGAME_MSG = true,

    -- (Opsional) Discord Webhook langsung untuk backup notifikasi ke channel Discord
    DISCORD_WEBHOOK_URL = ""
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
print("==================================================")

-- Aktifkan auto reconnect bawaan Lucifer
bot.auto_reconnect = true

-- Cache memori untuk mencegah double-trigger jika game mengirimkan pesan duplikat
local recent_cache = {}

-- Fungsi untuk membersihkan cache lama dan cek duplikasi
local function isDuplicate(growid, count, item_name)
    local now = os.time()
    local key = string.lower(growid) .. ":" .. count .. ":" .. string.lower(item_name)

    -- Hapus cache yang lebih dari 10 detik
    for k, timestamp in pairs(recent_cache) do
        if now - timestamp > 10 then
            recent_cache[k] = nil
        end
    end

    if recent_cache[key] and (now - recent_cache[key] <= 5) then
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

-- Fungsi mem-parsing teks donasi dari Donation Box
local function parseDonation(clean_text)
    local lower = string.lower(clean_text)
    if not (string.find(lower, "places") or string.find(lower, "deposited")) then
        return nil, nil, nil
    end

    -- Format Standar Growtopia:
    -- "[[FaruuXes places 1 World Lock into the Donation Box]]"
    -- "[Donation] UserGrowID deposited 2 Diamond Lock(s) into Donation Box."
    local growid, count_str, item_name = string.match(clean_text, "([%w_]+)%s+places%s+(%d+)%s+(.-)%s+into")

    if not growid then
        growid, count_str, item_name = string.match(clean_text, "([%w_]+)%s+deposited%s+(%d+)%s+(.-)%s+into")
    end

    if not growid then
        growid, count_str, item_name = string.match(clean_text, "([%w_]+)%s+places%s+(%d+)%s+(.-)$")
    end

    if not growid then
        growid, count_str, item_name = string.match(clean_text, "([%w_]+)%s+deposited%s+(%d+)%s+(.-)$")
    end

    if growid and count_str and item_name then
        local count = tonumber(count_str)
        -- Bersihkan nama item dari kurung (s) atau spasi berlebih
        item_name = string.gsub(item_name, "%(s%)", "")
        item_name = string.gsub(item_name, "^%s*(.-)%s*$", "%1")

        return growid, count, item_name
    end

    return nil, nil, nil
end

-- Fungsi mengirim data deposit ke Webhook Server Bot Discord
local function notifyServer(growid, count, item_name, amount_wl)
    local client = HttpClient.new()
    client.url = CONFIG.API_URL
    client:setMethod(Method.post)
    client.headers["Content-Type"] = "application/json"
    client.headers["X-GT-Token"] = CONFIG.SECRET_TOKEN

    local payload = string.format(
        '{"growid":"%s","item_name":"%s","count":%d,"amount_wl":%d,"world":"%s"}',
        growid, item_name, count, amount_wl, CONFIG.WORLD_NAME
    )
    client.content = payload
    client.timeout = 8

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
        print(string.format("[ERROR] Gagal mengirim deposit ke server. Status: %s, Error: %s", tostring(result.status), tostring(result.error)))
        return false
    end
end

-- Handler utama saat ada teks/pesan dari server Growtopia
local function handleMessage(raw_message)
    if not raw_message or raw_message == "" then
        return
    end

    -- Gunakan fungsi bawaan Lucifer untuk menghapus format warna Growtopia
    local clean = removeColor(raw_message)
    local lower = string.lower(clean)

    -- Cek apakah pesan berkaitan dengan donasi box (bisa 'places' atau 'deposited')
    if (string.find(lower, "places") or string.find(lower, "deposited")) and string.find(lower, "donation box") then
        local growid, count, raw_item = parseDonation(clean)
        if growid and count and raw_item then
            local rate, valid_item_name = getItemRate(raw_item)
            if rate > 0 and valid_item_name then
                -- Cegah pemrosesan ganda
                if not isDuplicate(growid, count, valid_item_name) then
                    local total_wl = count * rate
                    print(string.format("[DONATION DETECTED] %s -> %d %s (=%d WL)", growid, count, valid_item_name, total_wl))
                    notifyServer(growid, count, valid_item_name, total_wl)
                end
            else
                print("[DONATION IGNORED] Item '" .. tostring(raw_item) .. "' bukan WL/DL/BGL. Diabaikan.")
            end
        end
    end
end

-- Daftarkan event game_message
addEvent(Event.game_message, function(msg)
    handleMessage(msg)
end)

-- Daftarkan event variantlist (OnConsoleMessage & OnTalkBubble)
addEvent(Event.variantlist, function(varlist, net_id)
    if varlist[1] == "OnConsoleMessage" and varlist[2] then
        handleMessage(varlist[2])
    elseif varlist[1] == "OnTalkBubble" and varlist[3] then
        handleMessage(varlist[3])
    end
end)

-- Callback saat script dihentikan
function on_stop(err)
    if err ~= "" then
        print("[LUCIFER STOPPED WITH ERROR] " .. err)
    else
        print("[LUCIFER STOPPED] Script dihentikan secara normal.")
    end
end

-- ==============================================================================
-- MAIN LOOP (Tetap berada di World Deposit & Menjaga Koneksi)
-- ==============================================================================
while true do
    if bot.status == BotStatus.online then
        -- Cek apakah bot berada di world tujuan
        if not bot:isInWorld(CONFIG.WORLD_NAME) then
            print("[INFO] Bot belum berada di world " .. CONFIG.WORLD_NAME .. ". Melakukan warp...")
            if CONFIG.DOOR_ID ~= "" then
                bot:warp(CONFIG.WORLD_NAME, CONFIG.DOOR_ID)
            else
                bot:warp(CONFIG.WORLD_NAME)
            end
            sleep(4000)
        else
            -- Bot sudah di world, dengarkan antrean event selama 5 detik
            listenEvents(5)
        end
    else
        print("[INFO] Menunggu bot online...")
        sleep(3000)
    end
    sleep(500)
end
