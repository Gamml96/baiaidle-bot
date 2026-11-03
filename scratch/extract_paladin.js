const fs = require('fs');

const content = fs.readFileSync('scratch_game/game.js', 'utf8');

// We know the pattern is: YDe={voc:"paladin",nodes:[...]}
const match = content.match(/\{voc:"paladin",nodes:\[[\s\S]*?\]\}/);
if (match) {
    const rawObjStr = match[0];
    // In game.js, pi(1) might be used. Let's see what pi is or evaluate with a sandbox
    const fn = new Function('pi', `return (${rawObjStr})`);
    const paladinData = fn((x) => x * 0.1);
    console.log("Extracted paladin:", paladinData.voc, "nodes count:", paladinData.nodes.length);
    fs.writeFileSync('scratch/paladin_tree.json', JSON.stringify(paladinData, null, 2), 'utf8');
    console.log("Successfully wrote scratch/paladin_tree.json");
} else {
    console.log("Match not found");
}

