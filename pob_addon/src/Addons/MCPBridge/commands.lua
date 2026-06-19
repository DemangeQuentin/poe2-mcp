-- MCP Bridge Command Handlers for Path of Building (PoE2)
-- https://github.com/HivemindOverlord/poe2-mcp
--
-- This module defines all command handlers that can be invoked via the MCP bridge.
-- Each handler receives a params table and returns (result, errorMessage).

MCPCommands = {}

-------------------------------------------------------------------------------
-- HELPER FUNCTIONS
-------------------------------------------------------------------------------

-- Get the active build instance (works in both live PoB and headless modes)
-- In live PoB: build global OR launch.main.modes["BUILD"]
-- In headless: build global from HeadlessWrapper
local function getActiveBuild()
    -- First try the global build variable (works in headless and sometimes live)
    if build and build.calcsTab then
        return build
    end

    -- Try launch.main.modes["BUILD"] (live PoB structure)
    if launch and launch.main and launch.main.modes then
        local buildMode = launch.main.modes["BUILD"]
        if buildMode and buildMode.calcsTab then
            return buildMode
        end
    end

    -- Fallback: check if launch.main itself is the build (some PoB versions)
    if launch and launch.main and launch.main.calcsTab then
        return launch.main
    end

    return nil
end

-- Check if a build is currently loaded
local function hasBuildLoaded()
    return getActiveBuild() ~= nil
end

-- Force calculation refresh if build has pending changes
-- Returns: activeBuild, errorMessage
local function ensureBuildReady()
    local activeBuild = getActiveBuild()
    if not activeBuild then
        return nil, "No build loaded"
    end

    -- If buildFlag is set, calculations need to be rebuilt
    if activeBuild.buildFlag then
        -- Force calculation refresh
        if activeBuild.calcsTab and activeBuild.calcsTab.BuildOutput then
            activeBuild.calcsTab:BuildOutput()
        end
        activeBuild.buildFlag = false
    end

    return activeBuild, nil
end

-- Trigger a frame update cycle (for async operations)
-- This is a no-op stub - in live PoB, the main loop handles this automatically
-- The bridge.lua hooks OnFrame which runs after each frame
local function triggerUpdate()
    -- In live PoB, we can't force a frame update synchronously
    -- The calculations will be ready on the next poll cycle
    -- For commands that need immediate results, use ensureBuildReady() instead

    -- If there's a global runCallback (headless mode), use it
    if runCallback then
        pcall(runCallback, "OnFrame")
    end
end

-- Get the main application object for mode switching
local function getMainObject()
    -- In live PoB, launch.main handles mode switching
    if launch and launch.main then
        return launch.main
    end

    -- Legacy/headless fallback
    if mainObject then
        return mainObject.main or mainObject
    end

    return nil
end

-------------------------------------------------------------------------------
-- SYSTEM COMMANDS
-------------------------------------------------------------------------------

-- Ping: Simple health check
function MCPCommands.ping(params)
    local activeBuild = getActiveBuild()
    return {
        status = "ok",
        version = MCPConfig.VERSION,
        pob_version = launch and launch.versionNumber or "unknown",
        build_loaded = activeBuild ~= nil,
        build_name = activeBuild and activeBuild.buildName or nil,
        uptime = MCPBridge and MCPBridge.getStatus().uptime or 0
    }
end

-- Get server status
function MCPCommands.status(params)
    return MCPBridge.getStatus()
end

-------------------------------------------------------------------------------
-- BUILD COMMANDS
-------------------------------------------------------------------------------

-- Get current build as XML or PoB code
function MCPCommands.get_build(params)
    local activeBuild = getActiveBuild()
    if not activeBuild then
        return nil, "No build loaded"
    end

    local format = params.format or "xml"
    local xmlText = activeBuild:SaveDB("code")

    if not xmlText then
        return nil, "Failed to generate build XML"
    end

    if format == "code" then
        local deflated = Deflate(xmlText)
        if not deflated then
            return nil, "Failed to compress build (Deflate not available)"
        end
        local encoded = common.base64.encode(deflated)
        local code = encoded:gsub("+", "-"):gsub("/", "_")
        return {
            code = code,
            format = "pob_code",
            name = activeBuild.buildName or "Unnamed"
        }
    else
        return {
            xml = xmlText,
            format = "xml",
            name = activeBuild.buildName or "Unnamed"
        }
    end
end

-- Load a build from XML or PoB code
function MCPCommands.load_build(params)
    local xmlText

    if params.code then
        -- Decode PoB code to XML
        local decoded = common.base64.decode(params.code:gsub("-", "+"):gsub("_", "/"))
        if not decoded then
            return nil, "Failed to decode base64"
        end
        xmlText = Inflate(decoded)
        if not xmlText then
            return nil, "Failed to decompress build (Inflate not available)"
        end
    elseif params.xml then
        xmlText = params.xml
    else
        return nil, "Missing 'code' or 'xml' parameter"
    end

    local buildName = params.name or "MCP Import"

    -- Get main application for mode switching
    local main = getMainObject()
    if not main then
        return nil, "Cannot access PoB main object - is PoB fully initialized?"
    end

    -- Load the build via SetMode
    -- SetMode(mode, subMode, buildName, buildXML)
    -- This queues the mode change for next frame
    if main.SetMode then
        main:SetMode("BUILD", false, buildName, xmlText)
    else
        return nil, "SetMode not available on main object"
    end

    -- Trigger update cycle
    triggerUpdate()

    -- Note: Due to async nature of SetMode, build may not be immediately available
    -- Caller should verify with ping() or get_calcs() after a brief delay
    return {
        success = true,
        name = buildName,
        note = "Build load queued. Use ping() to verify build_loaded status."
    }
end

-- Create a new empty build
function MCPCommands.new_build(params)
    local buildName = params.name or "MCP New Build"

    -- Get main application for mode switching
    local main = getMainObject()
    if not main then
        return nil, "Cannot access PoB main object - is PoB fully initialized?"
    end

    -- Create new build via SetMode (no XML = new build)
    if main.SetMode then
        main:SetMode("BUILD", false, buildName)
    else
        return nil, "SetMode not available on main object"
    end

    -- Trigger update cycle
    triggerUpdate()

    return {
        success = true,
        name = buildName,
        note = "New build created. Use ping() to verify build_loaded status."
    }
end

-------------------------------------------------------------------------------
-- DIRECT BUILD MANIPULATION COMMANDS
-------------------------------------------------------------------------------

-- Load build XML directly into existing build (faster, no mode switch)
-- This is faster than load_build() when you already have a build loaded
function MCPCommands.load_build_direct(params)
    local activeBuild = getActiveBuild()
    if not activeBuild then
        return nil, "No build loaded - use load_build() first or open a build in PoB"
    end

    local xmlText
    if params.code then
        -- Decode PoB code to XML
        local decoded = common.base64.decode(params.code:gsub("-", "+"):gsub("_", "/"))
        if not decoded then
            return nil, "Failed to decode base64"
        end
        xmlText = Inflate(decoded)
        if not xmlText then
            return nil, "Failed to decompress build (Inflate not available)"
        end
    elseif params.xml then
        xmlText = params.xml
    else
        return nil, "Missing 'code' or 'xml' parameter"
    end

    -- Load directly into existing build
    local loadResult = activeBuild:LoadDB(xmlText, "MCP Direct Import")
    if loadResult == false then
        return nil, "Failed to load build XML - invalid format or version mismatch"
    end

    -- Force recalculation
    if activeBuild.buildFlag then
        if activeBuild.calcsTab and activeBuild.calcsTab.BuildOutput then
            activeBuild.calcsTab:BuildOutput()
        end
        activeBuild.buildFlag = false
    end

    return {
        success = true,
        name = activeBuild.buildName or "Unknown",
        method = "direct"
    }
end

-- Force full calculation refresh
function MCPCommands.recalculate(params)
    local activeBuild = getActiveBuild()
    if not activeBuild then
        return nil, "No build loaded"
    end

    if not activeBuild.calcsTab then
        return nil, "Build has no calcsTab - calculation not available"
    end

    -- Force rebuild by setting buildFlag
    activeBuild.buildFlag = true

    -- Perform calculation
    if activeBuild.calcsTab.BuildOutput then
        activeBuild.calcsTab:BuildOutput()
    end
    activeBuild.buildFlag = false

    -- Also rebuild config if available
    if activeBuild.configTab and activeBuild.configTab.BuildModList then
        activeBuild.configTab:BuildModList()
    end

    return {
        success = true,
        message = "Calculations refreshed"
    }
end

-------------------------------------------------------------------------------
-- CALCULATION COMMANDS
-------------------------------------------------------------------------------

-- Get calculation output (DPS, defenses, etc.)
function MCPCommands.get_calcs(params)
    -- Ensure build is ready and calculations are current
    local activeBuild, err = ensureBuildReady()
    if not activeBuild then
        return nil, err
    end

    if not activeBuild.calcsTab then
        return nil, "Build has no calcsTab - calculation not available"
    end

    local output = activeBuild.calcsTab.mainOutput or {}
    local calcsOutput = activeBuild.calcsTab.calcsOutput or {}

    -- Compile key stats
    local result = {
        -- Character info
        level = activeBuild.characterLevel,
        class = activeBuild.spec and activeBuild.spec.curClassName,
        ascendancy = activeBuild.spec and activeBuild.spec.curAscendClassName,

        -- Offensive stats
        TotalDPS = output.TotalDPS,
        CombinedDPS = output.CombinedDPS,
        AverageDamage = output.AverageDamage,
        Speed = output.Speed,
        CritChance = output.CritChance,
        CritMultiplier = output.CritMultiplier,
        HitChance = output.HitChance,
        Accuracy = output.Accuracy,

        -- Defensive stats
        Life = output.Life,
        LifeRegen = output.LifeRegen,
        LifeRegenPercent = output.LifeRegenPercent,
        EnergyShield = output.EnergyShield,
        EnergyShieldRegen = output.EnergyShieldRegen,
        Mana = output.Mana,
        ManaRegen = output.ManaRegen,
        Armour = output.Armour,
        Evasion = output.Evasion,
        PhysicalDamageReduction = output.PhysicalDamageReduction,
        SpellSuppressionChance = output.SpellSuppressionChance,
        BlockChance = output.BlockChance,
        SpellBlockChance = output.SpellBlockChance,

        -- Resistances
        FireResist = output.FireResist,
        FireResistOverCap = output.FireResistOverCap,
        ColdResist = output.ColdResist,
        ColdResistOverCap = output.ColdResistOverCap,
        LightningResist = output.LightningResist,
        LightningResistOverCap = output.LightningResistOverCap,
        ChaosResist = output.ChaosResist,
        ChaosResistOverCap = output.ChaosResistOverCap,

        -- Resources
        Spirit = output.Spirit,
        SpiritReserved = output.SpiritReserved,
        SpiritReservedPercent = output.SpiritReservedPercent,

        -- Attributes
        Str = output.Str,
        Dex = output.Dex,
        Int = output.Int,

        -- Max hits (from calcsOutput)
        PhysicalMaximumHitTaken = calcsOutput.PhysicalMaximumHitTaken,
        FireMaximumHitTaken = calcsOutput.FireMaximumHitTaken,
        ColdMaximumHitTaken = calcsOutput.ColdMaximumHitTaken,
        LightningMaximumHitTaken = calcsOutput.LightningMaximumHitTaken,
        ChaosMaximumHitTaken = calcsOutput.ChaosMaximumHitTaken,
    }

    return result
end

-- Get full raw output (for advanced analysis)
function MCPCommands.get_raw_output(params)
    local activeBuild, err = ensureBuildReady()
    if not activeBuild then
        return nil, err
    end

    if not activeBuild.calcsTab then
        return nil, "Build has no calcsTab - calculation not available"
    end

    return {
        mainOutput = activeBuild.calcsTab.mainOutput,
        calcsOutput = activeBuild.calcsTab.calcsOutput
    }
end

-- Get comprehensive calculations (mainOutput + calcsOutput merged)
function MCPCommands.get_full_calcs(params)
    local activeBuild, err = ensureBuildReady()
    if not activeBuild then
        return nil, err
    end

    if not activeBuild.calcsTab then
        return nil, "Build has no calcsTab - calculation not available"
    end

    local mainOutput = activeBuild.calcsTab.mainOutput or {}
    local calcsOutput = activeBuild.calcsTab.calcsOutput or {}

    -- Merge both outputs for comprehensive data
    local result = {
        -- Character metadata
        build_name = activeBuild.buildName,
        level = activeBuild.characterLevel,
        class = activeBuild.spec and activeBuild.spec.curClassName,
        ascendancy = activeBuild.spec and activeBuild.spec.curAscendClassName,

        -- All mainOutput values
        main = mainOutput,

        -- All calcsOutput values (detailed breakdown)
        calcs = calcsOutput,

        -- Key aggregated stats for quick access
        summary = {
            -- Offense
            total_dps = mainOutput.TotalDPS,
            combined_dps = mainOutput.CombinedDPS,
            crit_chance = mainOutput.CritChance,
            crit_multi = mainOutput.CritMultiplier,
            hit_chance = mainOutput.HitChance,

            -- Defense
            life = mainOutput.Life,
            energy_shield = mainOutput.EnergyShield,
            armour = mainOutput.Armour,
            evasion = mainOutput.Evasion,
            block = mainOutput.BlockChance,
            spell_block = mainOutput.SpellBlockChance,

            -- Resistances (capped)
            fire_res = mainOutput.FireResist,
            cold_res = mainOutput.ColdResist,
            lightning_res = mainOutput.LightningResist,
            chaos_res = mainOutput.ChaosResist,

            -- Resources
            mana = mainOutput.Mana,
            spirit = mainOutput.Spirit,
            spirit_reserved = mainOutput.SpiritReserved
        }
    }

    return result
end

-- Get DPS breakdown per skill group
function MCPCommands.get_skill_dps(params)
    local activeBuild, err = ensureBuildReady()
    if not activeBuild then
        return nil, err
    end

    if not activeBuild.skillsTab then
        return nil, "Build has no skillsTab"
    end

    if not activeBuild.calcsTab then
        return nil, "Build has no calcsTab - calculation not available"
    end

    local skills = {}
    local mainOutput = activeBuild.calcsTab.mainOutput or {}

    -- Get DPS for each skill group
    for i, socketGroup in ipairs(activeBuild.skillsTab.socketGroupList) do
        local skillInfo = {
            index = i,
            label = socketGroup.label or "",
            slot = socketGroup.slot,
            enabled = socketGroup.enabled,
            is_main = (i == activeBuild.mainSocketGroup),
            gems = {}
        }

        -- List gems in this group
        for j, gem in ipairs(socketGroup.gemList) do
            table.insert(skillInfo.gems, {
                name = gem.nameSpec,
                level = gem.level,
                quality = gem.quality,
                enabled = gem.enabled
            })
        end

        -- If this is the main skill, it has the DPS from mainOutput
        if skillInfo.is_main then
            skillInfo.dps = {
                total = mainOutput.TotalDPS,
                combined = mainOutput.CombinedDPS,
                average_hit = mainOutput.AverageDamage,
                speed = mainOutput.Speed,
                crit_chance = mainOutput.CritChance,
                crit_multi = mainOutput.CritMultiplier
            }
        end

        table.insert(skills, skillInfo)
    end

    return {
        skills = skills,
        main_skill_index = activeBuild.mainSocketGroup
    }
end

-- Get focused defense stats
function MCPCommands.get_defense_stats(params)
    local activeBuild, err = ensureBuildReady()
    if not activeBuild then
        return nil, err
    end

    if not activeBuild.calcsTab then
        return nil, "Build has no calcsTab - calculation not available"
    end

    local output = activeBuild.calcsTab.mainOutput or {}
    local calcsOutput = activeBuild.calcsTab.calcsOutput or {}

    return {
        -- Health pools
        life = {
            total = output.Life,
            regen = output.LifeRegen,
            regen_percent = output.LifeRegenPercent,
            leech_rate = output.LifeLeechRate,
            leech_max = output.MaxLifeLeechRate
        },
        energy_shield = {
            total = output.EnergyShield,
            regen = output.EnergyShieldRegen,
            recharge = output.EnergyShieldRecharge,
            recharge_delay = output.EnergyShieldRechargeDelay
        },
        mana = {
            total = output.Mana,
            unreserved = output.ManaUnreserved,
            regen = output.ManaRegen,
            reserved = output.ManaReserved,
            reserved_percent = output.ManaReservedPercent
        },

        -- Mitigation
        armour = {
            total = output.Armour,
            phys_reduction = output.PhysicalDamageReduction
        },
        evasion = {
            total = output.Evasion,
            chance = output.EvadeChance
        },
        block = {
            attack = output.BlockChance,
            spell = output.SpellBlockChance
        },
        suppression = {
            chance = output.SpellSuppressionChance,
            effect = output.SpellSuppressionEffect
        },

        -- Resistances (with overcap)
        resistances = {
            fire = { current = output.FireResist, overcap = output.FireResistOverCap },
            cold = { current = output.ColdResist, overcap = output.ColdResistOverCap },
            lightning = { current = output.LightningResist, overcap = output.LightningResistOverCap },
            chaos = { current = output.ChaosResist, overcap = output.ChaosResistOverCap }
        },

        -- Maximum hit taken
        max_hit = {
            physical = calcsOutput.PhysicalMaximumHitTaken,
            fire = calcsOutput.FireMaximumHitTaken,
            cold = calcsOutput.ColdMaximumHitTaken,
            lightning = calcsOutput.LightningMaximumHitTaken,
            chaos = calcsOutput.ChaosMaximumHitTaken
        },

        -- Stun/recovery
        stun = {
            threshold = output.StunThreshold,
            duration = output.StunDuration,
            recovery = output.StunRecovery
        }
    }
end

-------------------------------------------------------------------------------
-- SKILL COMMANDS
-------------------------------------------------------------------------------

-- Get all skill groups
function MCPCommands.get_skills(params)
    local activeBuild = getActiveBuild()
    if not activeBuild then
        return nil, "No build loaded"
    end

    if not activeBuild.skillsTab then
        return nil, "Build has no skillsTab"
    end

    local skillGroups = {}
    for i, socketGroup in ipairs(activeBuild.skillsTab.socketGroupList) do
        local gems = {}
        for j, gemInstance in ipairs(socketGroup.gemList) do
            table.insert(gems, {
                name = gemInstance.nameSpec,
                level = gemInstance.level,
                quality = gemInstance.quality,
                enabled = gemInstance.enabled,
                skillId = gemInstance.skillId
            })
        end
        table.insert(skillGroups, {
            index = i,
            slot = socketGroup.slot,
            label = socketGroup.label,
            enabled = socketGroup.enabled,
            isMainGroup = (i == activeBuild.mainSocketGroup),
            gems = gems
        })
    end

    return {
        skillGroups = skillGroups,
        mainSocketGroup = activeBuild.mainSocketGroup
    }
end

-- Add or replace a skill group
function MCPCommands.set_skill_group(params)
    local activeBuild = getActiveBuild()
    if not activeBuild then
        return nil, "No build loaded"
    end

    if not activeBuild.skillsTab then
        return nil, "Build has no skillsTab"
    end

    local skillText = params.skills
    if not skillText then
        return nil, "Missing 'skills' parameter"
    end

    -- Clear existing skills if requested
    if params.replace_all then
        while #activeBuild.skillsTab.socketGroupList > 0 do
            activeBuild.skillsTab:DeleteSocketGroup(activeBuild.skillsTab.socketGroupList[1])
        end
    end

    -- Paste the new skill group
    -- Format: "SkillName Level/Quality\nSupportName Level/Quality\n..."
    activeBuild.skillsTab:PasteSocketGroup(skillText)
    triggerUpdate()

    return { success = true }
end

-------------------------------------------------------------------------------
-- PASSIVE TREE COMMANDS
-------------------------------------------------------------------------------

-- Get allocated passive nodes
function MCPCommands.get_passive_tree(params)
    local activeBuild = getActiveBuild()
    if not activeBuild then
        return nil, "No build loaded"
    end

    if not activeBuild.spec then
        return nil, "Build has no spec"
    end

    local allocatedNodes = {}
    for nodeId, node in pairs(activeBuild.spec.allocNodes) do
        table.insert(allocatedNodes, {
            id = nodeId,
            name = node.name,
            type = node.type,
            isKeystone = node.isKeystone,
            isNotable = node.isNotable,
            isAscendancyStart = node.isAscendancyStart,
            ascendancyName = node.ascendancyName,
            stats = node.sd
        })
    end

    return {
        class = activeBuild.spec.curClassName,
        classId = activeBuild.spec.curClassId,
        ascendancy = activeBuild.spec.curAscendClassName,
        ascendancyId = activeBuild.spec.curAscendClassId,
        nodes = allocatedNodes,
        totalPoints = activeBuild.spec:CountAllocNodes()
    }
end

-- Allocate or deallocate a passive node
function MCPCommands.set_passive_node(params)
    local activeBuild = getActiveBuild()
    if not activeBuild then
        return nil, "No build loaded"
    end

    if not activeBuild.spec then
        return nil, "Build has no spec"
    end

    local nodeId = params.node_id
    if not nodeId then
        return nil, "Missing 'node_id' parameter"
    end

    local allocate = params.allocate
    if allocate == nil then
        allocate = true
    end

    if allocate then
        activeBuild.spec:AllocNode(nodeId)
    else
        activeBuild.spec:DeallocNode(nodeId)
    end

    activeBuild.spec:AddUndoState()
    triggerUpdate()

    return { success = true }
end

-------------------------------------------------------------------------------
-- ITEM COMMANDS
-------------------------------------------------------------------------------

-- Get equipped items
function MCPCommands.get_items(params)
    local activeBuild = getActiveBuild()
    if not activeBuild then
        return nil, "No build loaded"
    end

    if not activeBuild.itemsTab then
        return nil, "Build has no itemsTab"
    end

    local items = {}
    local slots = activeBuild.itemsTab.slots or {}

    for slotName, slot in pairs(slots) do
        local item = slot.selItemId and activeBuild.itemsTab.items[slot.selItemId]
        if item then
            table.insert(items, {
                slot = slotName,
                id = slot.selItemId,
                name = item.name,
                rarity = item.rarity,
                base = item.baseName,
                levelReq = item.levelReq,
                -- Include raw item text for full details
                rawText = item.raw
            })
        end
    end

    return { items = items }
end

-------------------------------------------------------------------------------
-- CONFIG COMMANDS
-------------------------------------------------------------------------------

-- Set custom modifiers
function MCPCommands.set_custom_mods(params)
    local activeBuild = getActiveBuild()
    if not activeBuild then
        return nil, "No build loaded"
    end

    if not activeBuild.configTab then
        return nil, "Build has no configTab"
    end

    local mods = params.mods or ""
    activeBuild.configTab.input.customMods = mods
    activeBuild.configTab:BuildModList()
    triggerUpdate()

    return { success = true }
end

-- Get custom modifiers
function MCPCommands.get_custom_mods(params)
    local activeBuild = getActiveBuild()
    if not activeBuild then
        return nil, "No build loaded"
    end

    if not activeBuild.configTab then
        return nil, "Build has no configTab"
    end

    return {
        mods = activeBuild.configTab.input.customMods or ""
    }
end

-- Set configuration option
function MCPCommands.set_config(params)
    local activeBuild = getActiveBuild()
    if not activeBuild then
        return nil, "No build loaded"
    end

    if not activeBuild.configTab then
        return nil, "Build has no configTab"
    end

    for key, value in pairs(params) do
        if key ~= "method" and key ~= "id" then
            activeBuild.configTab.input[key] = value
        end
    end

    activeBuild.configTab:BuildModList()
    triggerUpdate()

    return { success = true }
end

-- Get configuration options
function MCPCommands.get_config(params)
    local activeBuild = getActiveBuild()
    if not activeBuild then
        return nil, "No build loaded"
    end

    if not activeBuild.configTab then
        return nil, "Build has no configTab"
    end

    return {
        config = activeBuild.configTab.input
    }
end

-------------------------------------------------------------------------------
-- COMPARISON COMMANDS
-------------------------------------------------------------------------------

-- Compare current build with a snapshot (returns stat differences)
function MCPCommands.compare_with_snapshot(params)
    local activeBuild, err = ensureBuildReady()
    if not activeBuild then
        return nil, err
    end

    if not activeBuild.calcsTab then
        return nil, "Build has no calcsTab - calculation not available"
    end

    local snapshot = params.snapshot
    if not snapshot then
        return nil, "Missing 'snapshot' parameter (previous calcs)"
    end

    local current = MCPCommands.get_calcs({})
    if not current then
        return nil, "Failed to get current calculations"
    end

    local diff = {}
    for key, value in pairs(current) do
        if type(value) == "number" and snapshot[key] then
            local oldVal = snapshot[key]
            local delta = value - oldVal
            local pct = oldVal ~= 0 and (delta / oldVal * 100) or 0
            if math.abs(delta) > 0.001 then
                diff[key] = {
                    old = oldVal,
                    new = value,
                    delta = delta,
                    percent = pct
                }
            end
        end
    end

    return { diff = diff }
end

ConPrintf("[MCPBridge] Commands module loaded (%d commands)", (function()
    local count = 0
    for _ in pairs(MCPCommands) do count = count + 1 end
    return count
end)())
