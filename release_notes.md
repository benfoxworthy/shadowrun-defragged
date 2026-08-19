# *Shadowrun Defragged* Release Notes

## v1.0

### Core Patches
These changes are included in both *Defragged* and *Defragged Core*:

#### Gameplay Bugs
 - Fixed weapon attachments bug where combat calculations incorrectly indexed attachment bits using the weapon's ID instead of its slot index, causing calculations for Smartgun, Laser Sight, and Gas Vents attachments to be scrambled. This fix reduces the effectiveness of Shotguns (they could incorrectly benefit from a Smartlink in many cases) and improves SMGs (they could almost never benefit from Gas Vents).
 - Fixed Firearms attacks dealing damage even when 0 successes are rolled.
 - Fixed a melee defense underflow bug that caused instant death when attacked in melee with Wired Reflexes or certain other cyberware installed.
 - Fixed Muscle Replacement not affecting any Quickness calculations. The modified Quickness score is now used for movement speed, combat speed, combat and cybercombat success, and eight scripted events.
 - Fixed Protection Talismans and Rockskin incorrectly reducing damage dealt instead of damage taken.
 - Fixed entering shops or certain dialogues causing Tar Pit / Tar Paper to activate instantly when next encountered.
 - Fixed a stuck state that could occur after killing Thon with Mental damage. Instead, Mental damage to Thon is converted into Physical when it would otherwise be fatal.
 - Thon no longer suffers drain from his spell and can cast it indefinitely, preventing him from getting stuck with no valid attacks after casting his spell 9 times during the final battle. This also makes him hit harder - previously his drained mental health gave him target number penalties after the third attack.
 - Fixed several bugs in the Lone Star random encounter:
    - The Allegiance Shotgun is now correctly detected and confiscated as illegal during Lone Star searches.
    - The Lined Duster now conceals illegal weapons during Lone Star searches. Previously this was not implemented at all.
    - Fixed a bug where running away from Lone Star was more difficult if Joshua was wearing a Lined Duster (+1 TN) or Light Combat Armor (+2 TN). The penalty is now applied to Light Combat Armor (+1 TN) and Heavy Combat Armor (+2 TN), not the Lined Duster.
    - Having heat with Lone Star now makes the "answer all their questions convincingly" check harder, rather than easier.
 - Fixed "crashed CPU" flag never being cleared on map transitions. Now, crashing a CPU in the Matrix only disables Maglock doors when done from inside a corp building during a run.
 - The "Hack the management database" random event inside corp runs now uses the party's highest Computer skill instead of only Joshua's.
 - Fixed spells leaking visual effect slots, eventually causing all spells and firearms attacks to fail. This occurred most often when multiple spell casters were in the party. This fix also addresses a rare bug where Confusion or Stink could become invisibly stuck on a target indefinitely (including on a party member) until the spell was cast again and completed.
 - Fixed repeated spell casts restarting an enemy's death animation, which could sometimes keep dying enemies stuck indefinitely.
 - Fixed Spell Foci, Power Foci, and Fetishes not working when placed in Inventory Slot 8 (the bottom-right slot).

#### UI/Display Bugs
 - Fixed stuck "1" rendered in the Attributes/Skills screen when switching characters while an attribute is 10 or higher.
 - Fixed a display bug where the Magic screen would calculate success pips using the Spell Focus for the wrong spell when the spell was in the bottom row of icons.
 - The Contacts entry for Agira Tetsumi now correctly says "Offers Lvl 4 Power Focus" instead of "Lvl 3".
 - Fixed corrupted UI state in the Contacts screen if you visited a gang leader before obtaining a single Contact.
 - Fixed corrupted graphics in the Defense displays when the user's defense value exceeds the number of pips on screen; the value clamps instead. This is needed because several other fixes increase the amount of obtainable defense dice for Physical and/or Magic defenses.
 - Fixed corrupted graphics on the HUD's mental health bar that could occur after a spell caster in the party reaches low mental health.
 - Updated Sorcery tooltip to explain an obscure shared spell defense mechanic: "Sorcery determines success with spell casting and improves group spell defense."
 - Updated the Slow software tooltip to clarify that you can defeat ICs with it: "Slows an IC's attacks and alerts. Does not slow traces. Slowing an IC enough will defeat it."

### Additional Patches
Included in the full *Defragged* patch only and excluded from *Defragged Core*:

#### Gameplay Bugs
These additional fixes are most likely bugs, but deemed too ambiguous to be included in Core Patches:
 - Dermal Plating's increases to Body score now apply to physical magic damage resistance, not just guns/grenades/melee.
     - This is arguably a bug because it shows a modified Body score on the Attribute/Skills screen, but the description calls it "armor", which could reasonably not apply to spells.
 - A Power Focus now directly adds dice to the spell cast test, like a Spell Focus, instead of adding to the caster's effective Sorcery score. This means its offensive effect is no longer limited by the user's Magic score or current stance, and it no longer affects drain resistance or shared party spell defense. Only the highest rank Spell Focus or Power Focus is used. This matches the in-game description from Gregory Wilns: "much like a spell focus, with one exception. It increases the power of ANY spell".
     - This is arguably a bug based on the description, but there was no evidence in code that it was intended to work differently - its design was unintuitive, but correctly implemented.

#### Combat Balance
 - Reduced effectiveness of Gas Vents. The fixes to Weapon Attachments made SMGs extremely powerful. To compensate, Gas Vent II and III are now weaker: Gas Vent II now reduces TN by 1 instead of by 2, and Gas Vent III now reduces TN by 2/1/1 (based on which round in the burst) instead of by 3. This change makes an SMG with Gas Vent III less accurate than a Pistol, which helps balance the advantage of multiple attacks.
 - Protection Talismans now apply their rank as defensive resistance dice (like Body or Willpower) instead of applying half their rank as damage reduction (like Armor). This makes Protection Talisman Rank 3 better than Rank 2 (previously they were exactly the same due to rounding), prevents complete bullet immunity when combining Rank 4 with Heavy Combat Armor, and allows Protection Talismans to stack with Rockskin.
 - Rockskin cannot bring effective Ballistic Armor above 9, which prevents Heavy Combat Armor plus Rockskin making a character fully immune to Ballistic damage.
 - Hell Hound attacks and Thon's spells have been reduced from force 6 to force 5. This makes a high Body stat and shared group spell defense more effective at reducing damage.

#### Tar Pit & Deck Storage Rework
 - Tar Pit no longer permanently deletes a program. Instead, the program is removed from memory and can't be reloaded until your current Matrix run ends.
 - Deck Storage Refactor: Because Tar Pit no longer permanently deletes programs, storage upgrades have been expanded to prevent getting stuck with a deck full of unwanted programs.
   - Each deck can now always receive Storage upgrades equal to twice its MPCP rating. Previously this was inconsistent, with many decks unable to take Storage upgrades at all (possibly a bug).
   - Storage upgrades now add 50 MP each instead of 25, to avoid excessive clicks. The cost for the first rank has also been doubled to 200¥.
   - Storage upgrade costs now increase with each upgrade, to a max of 3,650¥ for Rank 24.
   - The Fairlight Excalibur now starts with 1,250 MP of storage instead of 1,000 MP. This means its maximum storage is 2,450 MP, which is enough to hold the max rank of every program plus data files.
