#!/usr/bin/env python3
"""
Gather character information using MCP and local game data
"""
import asyncio
import json
from pathlib import Path

async def main():
    from src.mcp_server import PoE2BuildOptimizerMCP
    
    # Initialize MCP
    mcp = PoE2BuildOptimizerMCP()
    await mcp.initialize()
    
    account_name = "3vort3x-2295"
    
    print(f"🎮 Gathering Character Information for: {account_name}")
    print("=" * 80)
    
    try:
        # Method 1: Read from local game Client.txt
        print("\n📖 Reading local game state from Client.txt...")
        
        from src.api.client_log_reader import ClientLogReader
        
        reader = ClientLogReader()
        
        if reader.is_available():
            print(f"✅ Client.txt found: {reader.log_path}")
            
            # Get current game state
            current_state = reader.get_current_state()
            
            if current_state and current_state.get('available'):
                print(f"\n📊 CURRENT GAME STATE:")
                print("=" * 80)
                print(f"Character:        {current_state.get('character', 'N/A')}")
                print(f"Class:            {current_state.get('ascendancy_or_class', 'N/A')}")
                print(f"Level:            {current_state.get('level', 'N/A')}")
                print(f"Current Area:     {current_state.get('area_code', 'N/A')}")
                print(f"Area Level:       {current_state.get('area_level', 'N/A')}")
                print(f"Instance Server:  {current_state.get('instance_server', 'N/A')}")
                print(f"AFK Mode:         {current_state.get('afk', 'N/A')}")
                print(f"Deaths in Window: {current_state.get('deaths_in_window', 0)}")
                print(f"Last Event:       {current_state.get('last_event_time', 'N/A')}")
                
                # Store character name for API lookup
                current_char = current_state.get('character', None)
                current_level = current_state.get('level', None)
                
                if current_char and current_level:
                    print(f"\n✅ Found active character: {current_char} (Level {current_level})")
                    
                    # Get recent events
                    print(f"\n📜 Recent Events (last 20):")
                    recent_events = reader.get_recent_events(limit=20)
                    for idx, event in enumerate(recent_events, 1):
                        kind = event.get('kind', 'unknown')
                        ts = event.get('timestamp', 'N/A')
                        if kind == 'level_up':
                            print(f"  {idx}. [{ts}] Level up: {event.get('character')} → Level {event.get('level')}")
                        elif kind == 'area_change':
                            print(f"  {idx}. [{ts}] Area: {event.get('area_code')} (Lvl {event.get('area_level')})")
                        elif kind == 'death':
                            print(f"  {idx}. [{ts}] ⚠️  Death: {event.get('character')}")
                        elif kind == 'instance_connect':
                            print(f"  {idx}. [{ts}] Connected to: {event.get('server')}")
                        elif kind == 'afk':
                            print(f"  {idx}. [{ts}] AFK: {event.get('afk_state')}")
                        else:
                            print(f"  {idx}. [{ts}] {kind}: {event}")
                    
                    # Now try to fetch detailed data from the API
                    print(f"\n" + "=" * 80)
                    print("📡 Fetching detailed character data from API...")
                    
                    from src.api.character_fetcher import CharacterFetcher
                    from src.api.rate_limiter import RateLimiter
                    
                    rate_limiter = RateLimiter()
                    fetcher = CharacterFetcher(cache_manager=mcp.cache_manager, rate_limiter=rate_limiter)
                    
                    # Try to get character data (Standard league by default)
                    char_data = await fetcher.get_character(account_name, current_char, league="Standard")
                    
                    if char_data:
                        print(f"\n✅ Full character data retrieved:")
                        print(json.dumps(char_data, indent=2, default=str))
                    else:
                        print(f"\n⚠️  Could not fetch full data from Standard league.")
                        print(f"    Character might be in a different league or private.")
                else:
                    print(f"\n⚠️  No active character in current game session")
                    print(f"    (Start a game to populate character data)")
            else:
                print(f"\n⚠️  Game state not available")
                print(f"    (Please start Path of Exile 2 or load a character)")
        else:
            print(f"❌ Client.txt not found")
            print(f"   Checked locations:")
            for loc in [
                "C:\\Program Files (x86)\\Steam\\steamapps\\common\\Path of Exile 2\\logs\\Client.txt",
                "C:\\Program Files\\Steam\\steamapps\\common\\Path of Exile 2\\logs\\Client.txt",
                "C:\\Program Files (x86)\\Grinding Gear Games\\Path of Exile 2\\logs\\Client.txt",
                "D:\\SteamLibrary\\steamapps\\common\\Path of Exile 2\\logs\\Client.txt",
            ]:
                exists = "✓" if Path(loc).exists() else "✗"
                print(f"   [{exists}] {loc}")
        
        print(f"\n" + "=" * 80)
        print("✅ Character information gathering complete!")
        
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(main())
