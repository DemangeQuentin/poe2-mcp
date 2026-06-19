-- MCP Bridge for Path of Building (PoE2)
-- TCP Socket Server for external tool communication
-- https://github.com/HivemindOverlord/poe2-mcp
--
-- This module creates a non-blocking TCP server that allows external tools
-- (like the poe2-mcp AI assistant) to query and control Path of Building.

local scriptPath = GetScriptPath()
local addonPath = scriptPath .. "/Addons/MCPBridge"

-- Load dependencies
local socket = require("socket")
local dkjson = require("dkjson")

-- Load config and commands
dofile(addonPath .. "/config.lua")
dofile(addonPath .. "/commands.lua")

-- Get config (loaded by config.lua)
local config = MCPConfig

-- Bridge state
local MCPBridge = {
    server = nil,
    running = false,
    lastError = nil,
    startTime = nil,
    requestCount = 0
}

-- Initialize the TCP server
function MCPBridge.start()
    if MCPBridge.running then
        ConPrintf("[MCPBridge] Already running on port %d", config.PORT)
        return true
    end

    -- Try to bind to the configured port
    local server, err = socket.bind(config.HOST, config.PORT)
    if not server then
        -- Try alternate ports if main port is busy
        for offset = 1, 3 do
            server, err = socket.bind(config.HOST, config.PORT + offset)
            if server then
                ConPrintf("[MCPBridge] Port %d busy, using %d", config.PORT, config.PORT + offset)
                config.PORT = config.PORT + offset
                break
            end
        end
    end

    if not server then
        MCPBridge.lastError = err
        ConPrintf("[MCPBridge] Failed to start server: %s", err)
        return false
    end

    -- Set non-blocking mode
    server:settimeout(config.TIMEOUT)

    MCPBridge.server = server
    MCPBridge.running = true
    MCPBridge.startTime = os.time()

    local host, port = server:getsockname()
    ConPrintf("[MCPBridge] Server started on %s:%d", host, port)

    return true
end

-- Stop the server
function MCPBridge.stop()
    if MCPBridge.server then
        MCPBridge.server:close()
        MCPBridge.server = nil
    end
    MCPBridge.running = false
    ConPrintf("[MCPBridge] Server stopped")
end

-- Send JSON-RPC response
local function sendResponse(client, id, result)
    local response = dkjson.encode({
        jsonrpc = "2.0",
        id = id,
        result = result
    })
    client:send(response .. "\n")
end

-- Send JSON-RPC error
local function sendError(client, id, code, message)
    local response = dkjson.encode({
        jsonrpc = "2.0",
        id = id,
        error = {
            code = code,
            message = message
        }
    })
    client:send(response .. "\n")
end

-- Handle incoming client connection
local function handleClient(client)
    client:settimeout(config.READ_TIMEOUT)

    -- Read the request line
    local request, err = client:receive("*l")
    if err then
        if err ~= "timeout" then
            ConPrintf("[MCPBridge] Receive error: %s", err)
        end
        return
    end

    -- Parse JSON-RPC request
    local success, command = pcall(dkjson.decode, request)
    if not success or not command then
        sendError(client, nil, -32700, "Parse error: Invalid JSON")
        return
    end

    if not command.method then
        sendError(client, command.id, -32600, "Invalid request: missing method")
        return
    end

    MCPBridge.requestCount = MCPBridge.requestCount + 1

    if config.LOG_COMMANDS then
        ConPrintf("[MCPBridge] Command: %s (id=%s)", command.method, tostring(command.id))
    end

    -- Look up and execute command handler
    local handler = MCPCommands[command.method]
    if handler then
        local ok, result, errMsg = pcall(handler, command.params or {})
        if ok then
            if errMsg then
                sendError(client, command.id, -32000, errMsg)
            else
                sendResponse(client, command.id, result)
            end
        else
            sendError(client, command.id, -32603, "Internal error: " .. tostring(result))
        end
    else
        sendError(client, command.id, -32601, "Method not found: " .. command.method)
    end
end

-- Poll for connections (called from main loop)
function MCPBridge.poll()
    if not MCPBridge.running or not MCPBridge.server then
        return
    end

    -- Accept new connection (non-blocking)
    local client, err = MCPBridge.server:accept()
    if client then
        local ok, handleErr = pcall(handleClient, client)
        if not ok then
            ConPrintf("[MCPBridge] Handler error: %s", tostring(handleErr))
        end
        client:close()
    end
end

-- Get server status
function MCPBridge.getStatus()
    return {
        running = MCPBridge.running,
        port = config.PORT,
        host = config.HOST,
        uptime = MCPBridge.startTime and (os.time() - MCPBridge.startTime) or 0,
        requests = MCPBridge.requestCount,
        lastError = MCPBridge.lastError,
        version = config.VERSION
    }
end

-- Hook into PoB's main loop
-- We need to inject our poll() call into the frame update cycle
local originalOnFrame = launch.OnFrame
launch.OnFrame = function(self)
    -- Call original OnFrame
    if originalOnFrame then
        originalOnFrame(self)
    end

    -- Poll for MCP connections
    if config.ENABLED then
        MCPBridge.poll()
    end
end

-- Hook into PoB's exit handler
local originalOnExit = launch.OnExit
launch.OnExit = function(self)
    -- Stop MCP bridge
    MCPBridge.stop()

    -- Call original OnExit
    if originalOnExit then
        originalOnExit(self)
    end
end

-- Auto-start if configured
if config.AUTO_START and config.ENABLED then
    -- Delay start slightly to ensure PoB is fully initialized
    -- We'll start on first frame instead
    local startAttempted = false
    local originalPoll = MCPBridge.poll
    MCPBridge.poll = function()
        if not startAttempted then
            startAttempted = true
            MCPBridge.start()
        end
        if MCPBridge.running then
            -- Restore original poll and call it
            MCPBridge.poll = originalPoll
            MCPBridge.poll()
        end
    end
end

-- Export for use by commands
_G.MCPBridge = MCPBridge

ConPrintf("[MCPBridge] Module loaded (v%s)", config.VERSION)
