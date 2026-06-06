// Reactions
const REACTIONS = [
    // Most common
    {name:"thumbsup",         label:"Thumbs Up",          emoji:"👍"},
    {name:"thumbsdown",       label:"Thumbs Down",        emoji:"👎"},
    {name:"heart",            label:"Heart",              emoji:"❤️"},
    {name:"laugh",            label:"Laugh",              emoji:"😂"},
    {name:"fire",             label:"Fire",               emoji:"🔥"},
    {name:"check",            label:"Check",              emoji:"✅"},
    {name:"eyes",             label:"Eyes",               emoji:"👀"},
    {name:"party",            label:"Party",              emoji:"🎉"},
    {name:"sad",              label:"Sad",                emoji:"😢"},
    {name:"wow",              label:"Wow",                emoji:"😮"},
    // Happy faces
    {name:"smile",            label:"Smile",              emoji:"😊"},
    {name:"grinning",         label:"Grinning",           emoji:"😁"},
    {name:"rofl",             label:"ROFL",               emoji:"🤣"},
    {name:"heart_eyes",       label:"Heart Eyes",         emoji:"😍"},
    {name:"star_struck",      label:"Star Struck",        emoji:"🤩"},
    {name:"wink",             label:"Wink",               emoji:"😉"},
    {name:"slightly_smile",   label:"Slightly Smiling",   emoji:"🙂"},
    {name:"upside_down",      label:"Upside Down",        emoji:"🙃"},
    {name:"sunglasses",       label:"Sunglasses",         emoji:"😎"},
    {name:"nerd",             label:"Nerd",               emoji:"🤓"},
    {name:"cowboy",           label:"Cowboy",             emoji:"🤠"},
    {name:"innocent",         label:"Innocent",           emoji:"😇"},
    {name:"partying",         label:"Partying",           emoji:"🥳"},
    {name:"sweat_smile",      label:"Sweat Smile",        emoji:"😅"},
    {name:"hugging",          label:"Hugging",            emoji:"🤗"},
    {name:"relieved",         label:"Relieved",           emoji:"😌"},
    {name:"money_mouth",      label:"Money Mouth",        emoji:"🤑"},
    // Neutral / expressive
    {name:"thinking",         label:"Thinking",           emoji:"🤔"},
    {name:"neutral",          label:"Neutral",            emoji:"😐"},
    {name:"smirk",            label:"Smirk",              emoji:"😏"},
    {name:"monocle",          label:"Monocle",            emoji:"🧐"},
    {name:"shushing",         label:"Shushing",           emoji:"🤫"},
    {name:"tongue",           label:"Tongue",             emoji:"😛"},
    {name:"zipper",           label:"Zipper Mouth",       emoji:"🤐"},
    {name:"raised_eyebrow",   label:"Raised Eyebrow",     emoji:"🤨"},
    {name:"melting",          label:"Melting",            emoji:"🫠"},
    {name:"astonished",       label:"Astonished",         emoji:"😲"},
    // Sad / negative / intense
    {name:"crying",           label:"Crying",             emoji:"😭"},
    {name:"pleading",         label:"Pleading",           emoji:"🥺"},
    {name:"pensive",          label:"Pensive",            emoji:"😔"},
    {name:"worried",          label:"Worried",            emoji:"😟"},
    {name:"angry",            label:"Angry",              emoji:"😡"},
    {name:"rage",             label:"Rage",               emoji:"🤬"},
    {name:"triumph",          label:"Triumph",            emoji:"😤"},
    {name:"grimace",          label:"Grimace",            emoji:"😬"},
    {name:"confounded",       label:"Confounded",         emoji:"😖"},
    {name:"persevere",        label:"Persevere",          emoji:"😣"},
    {name:"anguished",        label:"Anguished",          emoji:"😧"},
    {name:"scream",           label:"Scream",             emoji:"😱"},
    {name:"sleeping",         label:"Sleeping",           emoji:"😴"},
    {name:"yawn",             label:"Yawn",               emoji:"🥱"},
    {name:"flushed",          label:"Flushed",            emoji:"😳"},
    {name:"dizzy",            label:"Dizzy",              emoji:"😵"},
    {name:"woozy",            label:"Woozy",              emoji:"🥴"},
    {name:"mind_blown",       label:"Mind Blown",         emoji:"🤯"},
    {name:"hot_face",         label:"Hot Face",           emoji:"🥵"},
    {name:"cold_face",        label:"Cold Face",          emoji:"🥶"},
    {name:"nauseated",        label:"Nauseated",          emoji:"🤢"},
    {name:"sneezing",         label:"Sneezing",           emoji:"🤧"},
    {name:"mask",             label:"Mask",               emoji:"😷"},
    {name:"broken_heart",     label:"Broken Heart",       emoji:"💔"},
    // Silly / fun
    {name:"skull",            label:"Skull",              emoji:"💀"},
    {name:"ghost",            label:"Ghost",              emoji:"👻"},
    {name:"robot",            label:"Robot",              emoji:"🤖"},
    {name:"alien",            label:"Alien",              emoji:"👽"},
    {name:"clown",            label:"Clown",              emoji:"🤡"},
    {name:"devil",            label:"Devil",              emoji:"😈"},
    {name:"poop",             label:"Poop",               emoji:"💩"},
    {name:"zombie",           label:"Zombie",             emoji:"🧟"},
    {name:"vampire",          label:"Vampire",            emoji:"🧛"},
    {name:"see_no_evil",      label:"See No Evil",        emoji:"🙈"},
    {name:"hear_no_evil",     label:"Hear No Evil",       emoji:"🙉"},
    {name:"speak_no_evil",    label:"Speak No Evil",      emoji:"🙊"},
    // Gestures
    {name:"clap",             label:"Clap",               emoji:"👏"},
    {name:"pray",             label:"Pray",               emoji:"🙏"},
    {name:"wave",             label:"Wave",               emoji:"👋"},
    {name:"muscle",           label:"Muscle",             emoji:"💪"},
    {name:"peace",            label:"Peace",              emoji:"✌️"},
    {name:"ok",               label:"OK",                 emoji:"👌"},
    {name:"raised_hands",     label:"Raised Hands",       emoji:"🙌"},
    {name:"cross_fingers",    label:"Cross Fingers",      emoji:"🤞"},
    {name:"salute",           label:"Salute",             emoji:"🫡"},
    {name:"point_up",         label:"Point Up",           emoji:"☝️"},
    {name:"point_right",      label:"Point Right",        emoji:"👉"},
    {name:"point_left",       label:"Point Left",         emoji:"👈"},
    {name:"point_down",       label:"Point Down",         emoji:"👇"},
    {name:"call_me",          label:"Call Me",            emoji:"🤙"},
    {name:"love_you",         label:"Love You",           emoji:"🤟"},
    {name:"vulcan",           label:"Vulcan Salute",      emoji:"🖖"},
    {name:"open_hands",       label:"Open Hands",         emoji:"👐"},
    {name:"handshake",        label:"Handshake",          emoji:"🤝"},
    {name:"fist",             label:"Fist",               emoji:"✊"},
    {name:"pinch",            label:"Pinch",              emoji:"🤌"},
    {name:"writing",          label:"Writing",            emoji:"✍️"},
    // Hearts
    {name:"heart_purple",     label:"Purple Heart",       emoji:"💜"},
    {name:"heart_yellow",     label:"Yellow Heart",       emoji:"💛"},
    {name:"heart_green",      label:"Green Heart",        emoji:"💚"},
    {name:"heart_blue",       label:"Blue Heart",         emoji:"💙"},
    {name:"heart_orange",     label:"Orange Heart",       emoji:"🧡"},
    {name:"heart_white",      label:"White Heart",        emoji:"🤍"},
    {name:"heart_black",      label:"Black Heart",        emoji:"🖤"},
    {name:"heart_brown",      label:"Brown Heart",        emoji:"🤎"},
    {name:"heart_pink",       label:"Pink Heart",         emoji:"🩷"},
    {name:"heart_grow",       label:"Growing Heart",      emoji:"💗"},
    {name:"two_hearts",       label:"Two Hearts",         emoji:"💕"},
    {name:"revolving_hearts", label:"Revolving Hearts",   emoji:"💞"},
    {name:"sparkling_heart",  label:"Sparkling Heart",    emoji:"💖"},
    {name:"heart_box",        label:"Heart Box",          emoji:"💝"},
    // Objects & symbols
    {name:"sparkle",          label:"Sparkle",            emoji:"✨"},
    {name:"tada",             label:"Tada",               emoji:"🎊"},
    {name:"star",             label:"Star",               emoji:"⭐"},
    {name:"crown",            label:"Crown",              emoji:"👑"},
    {name:"trophy",           label:"Trophy",             emoji:"🏆"},
    {name:"medal",            label:"Medal",              emoji:"🥇"},
    {name:"gem",              label:"Gem",                emoji:"💎"},
    {name:"money",            label:"Money",              emoji:"💰"},
    {name:"rocket",           label:"Rocket",             emoji:"🚀"},
    {name:"zap",              label:"Zap",                emoji:"⚡"},
    {name:"bulb",             label:"Bulb",               emoji:"💡"},
    {name:"rainbow",          label:"Rainbow",            emoji:"🌈"},
    {name:"target",           label:"Target",             emoji:"🎯"},
    {name:"brain",            label:"Brain",              emoji:"🧠"},
    {name:"warning",          label:"Warning",            emoji:"⚠️"},
    {name:"no",               label:"No",                 emoji:"🚫"},
    {name:"lock",             label:"Lock",               emoji:"🔒"},
    {name:"key",              label:"Key",                emoji:"🔑"},
    {name:"magnify",          label:"Magnify",            emoji:"🔍"},
    {name:"bell",             label:"Bell",               emoji:"🔔"},
    {name:"hammer",           label:"Hammer",             emoji:"🔨"},
    {name:"pin",              label:"Pin",                emoji:"📌"},
    {name:"chart",            label:"Chart Up",           emoji:"📈"},
    {name:"bug",              label:"Bug",                emoji:"🐛"},
    {name:"magnet",           label:"Magnet",             emoji:"🧲"},
    {name:"dart",             label:"Dart",               emoji:"🎯"},
    {name:"die",              label:"Die",                emoji:"🎲"},
    {name:"hourglass",        label:"Hourglass",          emoji:"⌛"},
    {name:"crystal_ball",     label:"Crystal Ball",       emoji:"🔮"},
    {name:"joystick",         label:"Joystick",           emoji:"🕹️"},
    {name:"compass",          label:"Compass",            emoji:"🧭"},
    {name:"gift",             label:"Gift",               emoji:"🎁"},
    {name:"balloon",          label:"Balloon",            emoji:"🎈"},
    {name:"fireworks",        label:"Fireworks",          emoji:"🎆"},
    {name:"book",             label:"Book",               emoji:"📚"},
    {name:"pencil",           label:"Pencil",             emoji:"✏️"},
    {name:"wrench",           label:"Wrench",             emoji:"🔧"},
    {name:"gear",             label:"Gear",               emoji:"⚙️"},
    {name:"trash",            label:"Trash",              emoji:"🗑️"},
    {name:"package",          label:"Package",            emoji:"📦"},
    {name:"laptop",           label:"Laptop",             emoji:"💻"},
    {name:"phone",            label:"Phone",              emoji:"📱"},
    {name:"camera",           label:"Camera",             emoji:"📷"},
    {name:"newspaper",        label:"Newspaper",          emoji:"📰"},
    {name:"recycle",          label:"Recycle",            emoji:"♻️"},
    {name:"flag",             label:"Flag",               emoji:"🚩"},
    {name:"chess",            label:"Chess",              emoji:"♟️"},
    {name:"pill",             label:"Pill",               emoji:"💊"},
    {name:"bandage",          label:"Bandage",            emoji:"🩹"},
    {name:"toolbox",          label:"Toolbox",            emoji:"🧰"},
    {name:"candle",           label:"Candle",             emoji:"🕯️"},
    {name:"bomb",             label:"Bomb",               emoji:"💣"},
    {name:"shield",           label:"Shield",             emoji:"🛡️"},
    {name:"map",              label:"Map",                emoji:"🗺️"},
    {name:"scissors",         label:"Scissors",           emoji:"✂️"},
    {name:"stethoscope",      label:"Stethoscope",        emoji:"🩺"},
    {name:"gun",              label:"Water Gun",          emoji:"🔫"},
    // Science / tech
    {name:"atom",             label:"Atom",               emoji:"⚛️"},
    {name:"dna",              label:"DNA",                emoji:"🧬"},
    {name:"test_tube",        label:"Test Tube",          emoji:"🧪"},
    {name:"test_flask",       label:"Flask",              emoji:"⚗️"},
    {name:"microscope",       label:"Microscope",         emoji:"🔬"},
    {name:"telescope",        label:"Telescope",          emoji:"🔭"},
    // Music & arts
    {name:"guitar",           label:"Guitar",             emoji:"🎸"},
    {name:"drum",             label:"Drum",               emoji:"🥁"},
    {name:"piano",            label:"Piano",              emoji:"🎹"},
    {name:"trumpet",          label:"Trumpet",            emoji:"🎺"},
    {name:"violin",           label:"Violin",             emoji:"🎻"},
    {name:"microphone",       label:"Microphone",         emoji:"🎤"},
    {name:"headphones",       label:"Headphones",         emoji:"🎧"},
    {name:"clapper_board",    label:"Clapper Board",      emoji:"🎬"},
    {name:"palette",          label:"Palette",            emoji:"🎨"},
    {name:"yarn",             label:"Yarn",               emoji:"🧶"},
    {name:"gaming",           label:"Gaming",             emoji:"🎮"},
    {name:"music",            label:"Music",              emoji:"🎵"},
    // Sports & activities
    {name:"soccer",           label:"Soccer",             emoji:"⚽"},
    {name:"basketball",       label:"Basketball",         emoji:"🏀"},
    {name:"football",         label:"Football",           emoji:"🏈"},
    {name:"tennis",           label:"Tennis",             emoji:"🎾"},
    {name:"golf",             label:"Golf",               emoji:"⛳"},
    {name:"swim",             label:"Swimming",           emoji:"🏊"},
    {name:"yoga",             label:"Yoga",               emoji:"🧘"},
    {name:"bicycle",          label:"Bicycle",            emoji:"🚴"},
    {name:"ski",              label:"Skiing",             emoji:"⛷️"},
    {name:"surf",             label:"Surfing",            emoji:"🏄"},
    {name:"boxing",           label:"Boxing",             emoji:"🥊"},
    {name:"archery",          label:"Archery",            emoji:"🏹"},
    // Food & drinks
    {name:"pizza",            label:"Pizza",              emoji:"🍕"},
    {name:"coffee",           label:"Coffee",             emoji:"☕"},
    {name:"beer",             label:"Beer",               emoji:"🍺"},
    {name:"sushi",            label:"Sushi",              emoji:"🍣"},
    {name:"ramen",            label:"Ramen",              emoji:"🍜"},
    {name:"burger",           label:"Burger",             emoji:"🍔"},
    {name:"ice_cream",        label:"Ice Cream",          emoji:"🍦"},
    {name:"donut",            label:"Donut",              emoji:"🍩"},
    {name:"apple",            label:"Apple",              emoji:"🍎"},
    {name:"watermelon",       label:"Watermelon",         emoji:"🍉"},
    {name:"avocado",          label:"Avocado",            emoji:"🥑"},
    {name:"taco",             label:"Taco",               emoji:"🌮"},
    {name:"chocolate",        label:"Chocolate",          emoji:"🍫"},
    {name:"cake",             label:"Cake",               emoji:"🎂"},
    {name:"bread",            label:"Bread",              emoji:"🍞"},
    {name:"grapes",           label:"Grapes",             emoji:"🍇"},
    {name:"strawberry",       label:"Strawberry",         emoji:"🍓"},
    {name:"banana",           label:"Banana",             emoji:"🍌"},
    {name:"popcorn",          label:"Popcorn",            emoji:"🍿"},
    {name:"hot_dog",          label:"Hot Dog",            emoji:"🌭"},
    {name:"fries",            label:"Fries",              emoji:"🍟"},
    {name:"spaghetti",        label:"Spaghetti",          emoji:"🍝"},
    {name:"curry",            label:"Curry",              emoji:"🍛"},
    {name:"bento",            label:"Bento",              emoji:"🍱"},
    {name:"dumpling",         label:"Dumpling",           emoji:"🥟"},
    {name:"waffle",           label:"Waffle",             emoji:"🧇"},
    {name:"pancakes",         label:"Pancakes",           emoji:"🥞"},
    {name:"milk",             label:"Milk",               emoji:"🥛"},
    {name:"juice",            label:"Juice",              emoji:"🧃"},
    {name:"cocktail",         label:"Cocktail",           emoji:"🍹"},
    {name:"champagne",        label:"Champagne",          emoji:"🍾"},
    {name:"tea",              label:"Tea",                emoji:"🍵"},
    // Animals
    {name:"cat",              label:"Cat",                emoji:"🐱"},
    {name:"dog",              label:"Dog",                emoji:"🐶"},
    {name:"fox",              label:"Fox",                emoji:"🦊"},
    {name:"frog",             label:"Frog",               emoji:"🐸"},
    {name:"duck",             label:"Duck",               emoji:"🦆"},
    {name:"panda",            label:"Panda",              emoji:"🐼"},
    {name:"lion",             label:"Lion",               emoji:"🦁"},
    {name:"bear",             label:"Bear",               emoji:"🐻"},
    {name:"owl",              label:"Owl",                emoji:"🦉"},
    {name:"octopus",          label:"Octopus",            emoji:"🐙"},
    {name:"turtle",           label:"Turtle",             emoji:"🐢"},
    {name:"snake",            label:"Snake",              emoji:"🐍"},
    {name:"dinosaur",         label:"Dinosaur",           emoji:"🦖"},
    {name:"unicorn",          label:"Unicorn",            emoji:"🦄"},
    {name:"whale",            label:"Whale",              emoji:"🐳"},
    {name:"crab",             label:"Crab",               emoji:"🦀"},
    {name:"bee",              label:"Bee",                emoji:"🐝"},
    {name:"pig",              label:"Pig",                emoji:"🐷"},
    {name:"monkey",           label:"Monkey",             emoji:"🐵"},
    {name:"wolf",             label:"Wolf",               emoji:"🐺"},
    {name:"bat",              label:"Bat",                emoji:"🦇"},
    {name:"parrot",           label:"Parrot",             emoji:"🦜"},
    {name:"flamingo",         label:"Flamingo",           emoji:"🦩"},
    {name:"hedgehog",         label:"Hedgehog",           emoji:"🦔"},
    {name:"sloth",            label:"Sloth",              emoji:"🦥"},
    {name:"axolotl",          label:"Axolotl",            emoji:"🦎"},
    {name:"thread",           label:"Thread",             emoji:"🧵"},
    {name:"shrimp",           label:"Shrimp",             emoji:"🦐"},
    {name:"jellyfish",        label:"Jellyfish",          emoji:"🪼"},
    {name:"seal",             label:"Seal",               emoji:"🦭"},
    {name:"mammoth",          label:"Mammoth",            emoji:"🦣"},
    {name:"penguin",          label:"Penguin",            emoji:"🐧"},
    {name:"shark",            label:"Shark",              emoji:"🦈"},
    {name:"dragon",           label:"Dragon",             emoji:"🐉"},
    // Transport
    {name:"car",              label:"Car",                emoji:"🚗"},
    {name:"airplane",         label:"Airplane",           emoji:"✈️"},
    {name:"ship",             label:"Ship",               emoji:"🚢"},
    {name:"train",            label:"Train",              emoji:"🚂"},
    {name:"helicopter",       label:"Helicopter",         emoji:"🚁"},
    {name:"ufo",              label:"UFO",                emoji:"🛸"},
    {name:"canoe",            label:"Canoe",              emoji:"🛶"},
    // Nature & weather
    {name:"snowflake",        label:"Snowflake",          emoji:"❄️"},
    {name:"sun",              label:"Sun",                emoji:"☀️"},
    {name:"moon",             label:"Moon",               emoji:"🌙"},
    {name:"lightning",        label:"Lightning",          emoji:"🌩️"},
    {name:"cactus",           label:"Cactus",             emoji:"🌵"},
    {name:"four_leaf",        label:"Four Leaf Clover",   emoji:"🍀"},
    {name:"butterfly",        label:"Butterfly",          emoji:"🦋"},
    {name:"earth",            label:"Earth",              emoji:"🌍"},
    {name:"flower",           label:"Flower",             emoji:"🌺"},
    {name:"sunflower",        label:"Sunflower",          emoji:"🌻"},
    {name:"mushroom",         label:"Mushroom",           emoji:"🍄"},
    {name:"palm_tree",        label:"Palm Tree",          emoji:"🌴"},
    {name:"tornado",          label:"Tornado",            emoji:"🌪️"},
    {name:"cloud",            label:"Cloud",              emoji:"⛅"},
    {name:"volcano",          label:"Volcano",            emoji:"🌋"},
    {name:"desert",           label:"Desert",             emoji:"🏜️"},
    {name:"island",           label:"Island",             emoji:"🏝️"},
    {name:"mountain",         label:"Mountain",           emoji:"🏔️"},
    {name:"comet",            label:"Comet",              emoji:"☄️"},
    {name:"saturn",           label:"Saturn",             emoji:"🪐"},
    {name:"milky_way",        label:"Milky Way",          emoji:"🌌"},
    // More faces
    {name:"expressionless",   label:"Expressionless",     emoji:"😑"},
    {name:"no_mouth",         label:"No Mouth",           emoji:"😶"},
    {name:"rolling_eyes",     label:"Rolling Eyes",       emoji:"🙄"},
    {name:"hushed",           label:"Hushed",             emoji:"😯"},
    {name:"sleepy",           label:"Sleepy",             emoji:"😪"},
    {name:"drooling",         label:"Drooling",           emoji:"🤤"},
    {name:"lying",            label:"Lying",              emoji:"🤥"},
    {name:"exhaling",         label:"Exhaling",           emoji:"😮‍💨"},
    {name:"holding_back_tears", label:"Holding Back Tears", emoji:"🥹"},
    {name:"peeking",          label:"Peeking",            emoji:"🫣"},
    {name:"hand_over_mouth",  label:"Hand Over Mouth",    emoji:"🫢"},
    {name:"dotted_face",      label:"Dotted Face",        emoji:"🫥"},
    {name:"shaking_face",     label:"Shaking Face",       emoji:"🫨"},
    {name:"diagonal_mouth",   label:"Diagonal Mouth",     emoji:"🫤"},
    {name:"heart_on_fire",    label:"Heart on Fire",      emoji:"❤️‍🔥"},
    {name:"mending_heart",    label:"Mending Heart",      emoji:"❤️‍🩹"},
    // More gestures
    {name:"middle_finger",    label:"Middle Finger",      emoji:"🖕"},
    {name:"backhand_up",      label:"Backhand Point Up",  emoji:"👆"},
    {name:"raised_back",      label:"Raised Back of Hand",emoji:"🤚"},
    {name:"heart_hands",      label:"Heart Hands",        emoji:"🫶"},
    {name:"left_fist",        label:"Left Fist",          emoji:"🤛"},
    {name:"right_fist",       label:"Right Fist",         emoji:"🤜"},
    {name:"splayed_hand",     label:"Splayed Hand",       emoji:"🖐️"},
    {name:"palm_up",          label:"Palm Up",            emoji:"🫴"},
    {name:"palm_down",        label:"Palm Down",          emoji:"🫳"},
    {name:"point_at_you",     label:"Point at You",       emoji:"🫵"},
    // More animals
    {name:"horse",            label:"Horse",              emoji:"🐴"},
    {name:"cow",              label:"Cow",                emoji:"🐮"},
    {name:"sheep",            label:"Sheep",              emoji:"🐑"},
    {name:"goat",             label:"Goat",               emoji:"🐐"},
    {name:"rabbit",           label:"Rabbit",             emoji:"🐰"},
    {name:"hamster",          label:"Hamster",            emoji:"🐹"},
    {name:"mouse",            label:"Mouse",              emoji:"🐭"},
    {name:"chipmunk",         label:"Chipmunk",           emoji:"🐿️"},
    {name:"otter",            label:"Otter",              emoji:"🦦"},
    {name:"raccoon",          label:"Raccoon",            emoji:"🦝"},
    {name:"skunk",            label:"Skunk",              emoji:"🦨"},
    {name:"gorilla",          label:"Gorilla",            emoji:"🦍"},
    {name:"elephant",         label:"Elephant",           emoji:"🐘"},
    {name:"hippo",            label:"Hippo",              emoji:"🦛"},
    {name:"giraffe",          label:"Giraffe",            emoji:"🦒"},
    {name:"camel",            label:"Camel",              emoji:"🐪"},
    {name:"zebra",            label:"Zebra",              emoji:"🦓"},
    {name:"kangaroo",         label:"Kangaroo",           emoji:"🦘"},
    {name:"koala",            label:"Koala",              emoji:"🐨"},
    {name:"deer",             label:"Deer",               emoji:"🦌"},
    {name:"llama",            label:"Llama",              emoji:"🦙"},
    {name:"peacock",          label:"Peacock",            emoji:"🦚"},
    {name:"swan",             label:"Swan",               emoji:"🦢"},
    {name:"eagle",            label:"Eagle",              emoji:"🦅"},
    {name:"dove",             label:"Dove",               emoji:"🕊️"},
    {name:"rooster",          label:"Rooster",            emoji:"🐓"},
    {name:"fish",             label:"Fish",               emoji:"🐟"},
    {name:"tropical_fish",    label:"Tropical Fish",      emoji:"🐠"},
    {name:"dolphin",          label:"Dolphin",            emoji:"🐬"},
    {name:"lobster",          label:"Lobster",            emoji:"🦞"},
    {name:"squid",            label:"Squid",              emoji:"🦑"},
    {name:"snail",            label:"Snail",              emoji:"🐌"},
    {name:"worm",             label:"Worm",               emoji:"🪱"},
    {name:"oyster",           label:"Oyster",             emoji:"🦪"},
    {name:"rhino",            label:"Rhinoceros",         emoji:"🦏"},
    {name:"crocodile",        label:"Crocodile",          emoji:"🐊"},
    {name:"microbe",          label:"Microbe",            emoji:"🦠"},
    // More food & drink
    {name:"bagel",            label:"Bagel",              emoji:"🥯"},
    {name:"croissant",        label:"Croissant",          emoji:"🥐"},
    {name:"pretzel",          label:"Pretzel",            emoji:"🥨"},
    {name:"cheese",           label:"Cheese",             emoji:"🧀"},
    {name:"egg",              label:"Egg",                emoji:"🥚"},
    {name:"bacon",            label:"Bacon",              emoji:"🥓"},
    {name:"sandwich",         label:"Sandwich",           emoji:"🥪"},
    {name:"wrap",             label:"Wrap",               emoji:"🌯"},
    {name:"salad",            label:"Salad",              emoji:"🥗"},
    {name:"soup",             label:"Soup",               emoji:"🍲"},
    {name:"salt",             label:"Salt",               emoji:"🧂"},
    {name:"honey",            label:"Honey",              emoji:"🍯"},
    {name:"lollipop",         label:"Lollipop",           emoji:"🍭"},
    {name:"candy",            label:"Candy",              emoji:"🍬"},
    {name:"bubble_tea",       label:"Bubble Tea",         emoji:"🧋"},
    {name:"ice",              label:"Ice",                emoji:"🧊"},
    {name:"mate",             label:"Mate",               emoji:"🧉"},
    {name:"fortune_cookie",   label:"Fortune Cookie",     emoji:"🥠"},
    {name:"tamale",           label:"Tamale",             emoji:"🫔"},
    {name:"flatbread",        label:"Flatbread",          emoji:"🫓"},
    {name:"beans",            label:"Beans",              emoji:"🫘"},
    {name:"blueberries",      label:"Blueberries",        emoji:"🫐"},
    {name:"mango",            label:"Mango",              emoji:"🥭"},
    {name:"kiwi",             label:"Kiwi",               emoji:"🥝"},
    {name:"pear",             label:"Pear",               emoji:"🍐"},
    {name:"peach",            label:"Peach",              emoji:"🍑"},
    {name:"cherry",           label:"Cherry",             emoji:"🍒"},
    {name:"lemon",            label:"Lemon",              emoji:"🍋"},
    {name:"tangerine",        label:"Tangerine",          emoji:"🍊"},
    {name:"pineapple",        label:"Pineapple",          emoji:"🍍"},
    {name:"melon",            label:"Melon",              emoji:"🍈"},
    {name:"tomato",           label:"Tomato",             emoji:"🍅"},
    {name:"garlic",           label:"Garlic",             emoji:"🧄"},
    {name:"onion",            label:"Onion",              emoji:"🧅"},
    {name:"carrot",           label:"Carrot",             emoji:"🥕"},
    {name:"broccoli",         label:"Broccoli",           emoji:"🥦"},
    {name:"corn",             label:"Corn",               emoji:"🌽"},
    {name:"hot_pepper",       label:"Hot Pepper",         emoji:"🌶️"},
    // More sports & activities
    {name:"baseball",         label:"Baseball",           emoji:"⚾"},
    {name:"softball",         label:"Softball",           emoji:"🥎"},
    {name:"badminton",        label:"Badminton",          emoji:"🏸"},
    {name:"rugby",            label:"Rugby",              emoji:"🏉"},
    {name:"ping_pong",        label:"Ping Pong",          emoji:"🏓"},
    {name:"flying_disc",      label:"Flying Disc",        emoji:"🥏"},
    {name:"sled",             label:"Sled",               emoji:"🛷"},
    {name:"parachute",        label:"Parachute",          emoji:"🪂"},
    {name:"martial_arts",     label:"Martial Arts",       emoji:"🥋"},
    {name:"climbing",         label:"Climbing",           emoji:"🧗"},
    {name:"weightlifting",    label:"Weightlifting",      emoji:"🏋️"},
    {name:"skateboard",       label:"Skateboard",         emoji:"🛹"},
    {name:"lacrosse",         label:"Lacrosse",           emoji:"🥍"},
    {name:"ice_skate",        label:"Ice Skate",          emoji:"⛸️"},
    {name:"fishing",          label:"Fishing",            emoji:"🎣"},
    {name:"diving",           label:"Diving",             emoji:"🤿"},
    {name:"cards",            label:"Playing Cards",      emoji:"🃏"},
    // More music
    {name:"saxophone",        label:"Saxophone",          emoji:"🎷"},
    {name:"banjo",            label:"Banjo",              emoji:"🪕"},
    {name:"accordion",        label:"Accordion",          emoji:"🪗"},
    {name:"notes",            label:"Musical Notes",      emoji:"🎶"},
    {name:"long_drum",        label:"Long Drum",          emoji:"🪘"},
    // More vehicles
    {name:"motorcycle",       label:"Motorcycle",         emoji:"🏍️"},
    {name:"race_car",         label:"Race Car",           emoji:"🏎️"},
    {name:"speedboat",        label:"Speedboat",          emoji:"🚤"},
    {name:"sailboat",         label:"Sailboat",           emoji:"⛵"},
    {name:"bus",              label:"Bus",                emoji:"🚌"},
    {name:"truck",            label:"Truck",              emoji:"🚚"},
    {name:"fire_truck",       label:"Fire Truck",         emoji:"🚒"},
    {name:"ambulance",        label:"Ambulance",          emoji:"🚑"},
    {name:"tractor",          label:"Tractor",            emoji:"🚜"},
    {name:"motor_scooter",    label:"Motor Scooter",      emoji:"🛵"},
    // More nature & plants
    {name:"seedling",         label:"Seedling",           emoji:"🌱"},
    {name:"evergreen",        label:"Evergreen Tree",     emoji:"🌲"},
    {name:"deciduous",        label:"Deciduous Tree",     emoji:"🌳"},
    {name:"chestnut",         label:"Chestnut",           emoji:"🌰"},
    {name:"cherry_blossom",   label:"Cherry Blossom",     emoji:"🌸"},
    {name:"rose",             label:"Rose",               emoji:"🌹"},
    {name:"tulip",            label:"Tulip",              emoji:"🌷"},
    {name:"lotus",            label:"Lotus",              emoji:"🪷"},
    {name:"bouquet",          label:"Bouquet",            emoji:"💐"},
    {name:"wilted_flower",    label:"Wilted Flower",      emoji:"🥀"},
    {name:"herb",             label:"Herb",               emoji:"🌿"},
    {name:"maple_leaf",       label:"Maple Leaf",         emoji:"🍁"},
    {name:"leaves",           label:"Leaves",             emoji:"🍃"},
    {name:"water_wave",       label:"Water Wave",         emoji:"🌊"},
    {name:"droplet",          label:"Droplet",            emoji:"💧"},
    {name:"fog",              label:"Fog",                emoji:"🌫️"},
    {name:"cyclone",          label:"Cyclone",            emoji:"🌀"},
    {name:"umbrella",         label:"Umbrella",           emoji:"☔"},
    {name:"snowman",          label:"Snowman",            emoji:"⛄"},
    {name:"rainbow_flag",     label:"Rainbow Flag",       emoji:"🌈"},
    // More symbols & objects
    {name:"hundred",          label:"100",                emoji:"💯"},
    {name:"speech_bubble",    label:"Speech Bubble",      emoji:"💬"},
    {name:"thought_bubble",   label:"Thought Bubble",     emoji:"💭"},
    {name:"zzz",              label:"ZZZ",                emoji:"💤"},
    {name:"anger",            label:"Anger",              emoji:"💢"},
    {name:"red_circle",       label:"Red Circle",         emoji:"🔴"},
    {name:"blue_circle",      label:"Blue Circle",        emoji:"🔵"},
    {name:"green_circle",     label:"Green Circle",       emoji:"🟢"},
    {name:"infinity",         label:"Infinity",           emoji:"♾️"},
    {name:"syringe",          label:"Syringe",            emoji:"💉"},
    {name:"fire_extinguisher",label:"Fire Extinguisher",  emoji:"🧯"},
    {name:"safety_pin",       label:"Safety Pin",         emoji:"🧷"},
    {name:"broom",            label:"Broom",              emoji:"🧹"},
    {name:"soap",             label:"Soap",               emoji:"🧼"},
    {name:"nazar",            label:"Nazar Amulet",       emoji:"🧿"},
    {name:"teddy_bear",       label:"Teddy Bear",         emoji:"🧸"},
    {name:"magic_wand",       label:"Magic Wand",         emoji:"🪄"},
    {name:"kite",             label:"Kite",               emoji:"🪁"},
    {name:"yo_yo",            label:"Yo-Yo",              emoji:"🪀"},
    {name:"boomerang",        label:"Boomerang",          emoji:"🪃"},
    {name:"axe",              label:"Axe",                emoji:"🪓"},
    {name:"ladder",           label:"Ladder",             emoji:"🪜"},
    {name:"mirror",           label:"Mirror",             emoji:"🪞"},
    {name:"chair",            label:"Chair",              emoji:"🪑"},
    {name:"battery",          label:"Battery",            emoji:"🔋"},
    {name:"floppy",           label:"Floppy Disk",        emoji:"💾"},
    {name:"cd",               label:"CD",                 emoji:"💿"},
    {name:"globe",            label:"Globe",              emoji:"🌐"},
    {name:"satellite",        label:"Satellite",          emoji:"🛰️"},
    // Celebrations & holidays
    {name:"jack_o_lantern",   label:"Jack-o-Lantern",     emoji:"🎃"},
    {name:"christmas_tree",   label:"Christmas Tree",     emoji:"🎄"},
    {name:"sparkler",         label:"Sparkler",           emoji:"🎇"},
    {name:"firecracker",      label:"Firecracker",        emoji:"🧨"},
    {name:"ribbon",           label:"Ribbon",             emoji:"🎀"},
    {name:"ticket",           label:"Ticket",             emoji:"🎫"},
];

const REACTION_EMOJI = Object.fromEntries(REACTIONS.map(r => [r.name, r.emoji]));

(function buildPicker() {
    const grid = document.getElementById("reaction-picker-grid");
    REACTIONS.forEach(r => {
        const btn = document.createElement("button");
        btn.className = "reaction-picker-item";
        btn.title = r.label;
        btn.dataset.name = r.name;
        btn.dataset.label = r.label.toLowerCase();
        btn.onclick = function(e) { e.stopPropagation(); pickerReact(r.name); };
        const span = document.createElement("span");
        span.textContent = r.emoji;
        span.style.fontSize = "22px";
        btn.appendChild(span);
        grid.appendChild(btn);
    });
    const search = document.getElementById("reaction-search");
    search.addEventListener("input", function() { filterReactions(this.value); });
    search.addEventListener("click", function(e) { e.stopPropagation(); });
    search.addEventListener("keydown", function(e) {
        if (e.key === "Escape") { closeReactionPicker(); }
        else if (e.key === "Enter") {
            e.preventDefault();
            const first = Array.from(document.querySelectorAll(".reaction-picker-item")).find(el => el.style.display !== "none");
            if (first) first.click();
        }
    });
})();

function filterReactions(query) {
    const q = query.toLowerCase().trim();
    document.querySelectorAll(".reaction-picker-item").forEach(function(item) {
        const match = !q || item.dataset.name.includes(q) || item.dataset.label.includes(q);
        item.style.display = match ? "" : "none";
    });
}

let currentPickerMsgId = null;

function openReactionPicker(msgId, event) {
    event.stopPropagation();
    if (currentPickerMsgId !== null) {
        const prev = document.getElementById("msg-" + currentPickerMsgId);
        if (prev) prev.classList.remove("reaction-picker-open");
    }
    currentPickerMsgId = msgId;
    const msgEl = document.getElementById("msg-" + msgId);
    if (msgEl) msgEl.classList.add("reaction-picker-open");
    const picker = document.getElementById("reaction-picker");
    picker.style.display = "block";
    const btn = event.currentTarget;
    const rect = btn.getBoundingClientRect();
    const pw = picker.offsetWidth || 228;
    let left = rect.left;
    if (left + pw > window.innerWidth - 8) left = window.innerWidth - pw - 8;
    picker.style.top = (rect.bottom + 4) + "px";
    picker.style.left = left + "px";
    const search = document.getElementById("reaction-search");
    search.value = "";
    filterReactions("");
    requestAnimationFrame(function() { search.focus(); });
}

function closeReactionPicker() {
    document.getElementById("reaction-picker").style.display = "none";
    if (currentPickerMsgId !== null) {
        const msgEl = document.getElementById("msg-" + currentPickerMsgId);
        if (msgEl) msgEl.classList.remove("reaction-picker-open");
    }
    currentPickerMsgId = null;
}

function pickerReact(reactionName) {
    if (currentPickerMsgId === null) return;
    toggleReaction(currentPickerMsgId, reactionName);
    closeReactionPicker();
}

function buildReactionsHtml(msgId, reactionsJson) {
    let reactions;
    try { reactions = JSON.parse(reactionsJson || "{}"); } catch { reactions = {}; }
    let html = "";
    for (const name in reactions) {
        const users = reactions[name];
        if (!users || users.length === 0) continue;
        const isActive = users.includes(CURRENT_USER);
        const tooltip = escapeHtml(users.join(", "));
        html += `<span class="reaction-chip${isActive ? " active" : ""}" onclick="toggleReaction(${msgId}, '${name}')">`;
        html += `<span style="font-size:16px">${REACTION_EMOJI[name] || name}</span>`;
        html += `<span class="reaction-count">${users.length}</span>`;
        html += `<span class="reaction-tooltip">${tooltip}</span>`;
        html += `</span>`;
    }
    return html;
}

function toggleReaction(msgId, reactionName) {
    fetch(`/react/${msgId}`, {
        method: "POST",
        headers: {"Content-Type": "application/x-www-form-urlencoded"},
        body: new URLSearchParams({reaction: reactionName})
    })
    .then(res => {
        if (!res.ok) throw new Error("React failed");
        return res.json();
    })
    .then(reactions => {
        const div = document.getElementById("reactions-" + msgId);
        if (div) div.innerHTML = buildReactionsHtml(msgId, JSON.stringify(reactions));
    })
    .catch(err => console.error("Reaction error:", err));
}

document.addEventListener("click", function(e) {
    const picker = document.getElementById("reaction-picker");
    if (picker && picker.style.display !== "none" && !picker.contains(e.target)) {
        closeReactionPicker();
    }
});

// ── Emoji picker (inserts emoji into the message box) ────────────────────────
// Reuses the REACTIONS emoji set. Unlike the reaction picker, clicking an item
// inserts the character at the caret in the message box and leaves the picker
// open so several emoji can be added in a row.

(function buildEmojiPicker() {
    const grid = document.getElementById("emoji-picker-grid");
    if (!grid) return;
    REACTIONS.forEach(function(r) {
        const btn = document.createElement("button");
        btn.type = "button";
        btn.className = "emoji-picker-item";
        btn.title = r.label;
        btn.dataset.name = r.name;
        btn.dataset.label = r.label.toLowerCase();
        btn.textContent = r.emoji;
        btn.onclick = function(e) { e.stopPropagation(); insertEmoji(r.emoji); };
        grid.appendChild(btn);
    });
    const search = document.getElementById("emoji-search");
    search.addEventListener("input", function() { filterEmojis(this.value); });
    search.addEventListener("click", function(e) { e.stopPropagation(); });
    search.addEventListener("keydown", function(e) {
        if (e.key === "Escape") { closeEmojiPicker(); }
        else if (e.key === "Enter") {
            e.preventDefault();
            const first = Array.from(grid.querySelectorAll(".emoji-picker-item"))
                .find(el => el.style.display !== "none");
            if (first) first.click();
        }
    });
})();

function filterEmojis(query) {
    const q = query.toLowerCase().trim();
    document.querySelectorAll("#emoji-picker-grid .emoji-picker-item").forEach(function(item) {
        const match = !q || item.dataset.name.includes(q) || item.dataset.label.includes(q);
        item.style.display = match ? "" : "none";
    });
}

function insertEmoji(emoji) {
    const box = document.getElementById("msg");
    if (!box) return;
    const start = box.selectionStart ?? box.value.length;
    const end = box.selectionEnd ?? box.value.length;
    box.value = box.value.slice(0, start) + emoji + box.value.slice(end);
    box.selectionStart = box.selectionEnd = start + emoji.length;
    box.focus();
    // Notify the rest of the app (send-button state, typing indicator, …).
    box.dispatchEvent(new Event("input"));
}

function openEmojiPicker(event) {
    event.stopPropagation();
    const picker = document.getElementById("emoji-picker");
    if (picker.style.display === "block") { closeEmojiPicker(); return; }
    picker.style.display = "block";
    const rect = event.currentTarget.getBoundingClientRect();
    const pw = picker.offsetWidth;
    const ph = picker.offsetHeight;
    let left = Math.max(8, Math.min(rect.left, window.innerWidth - pw - 8));
    // The message box sits at the bottom, so open above the button.
    let top = rect.top - ph - 6;
    if (top < 8) top = rect.bottom + 6;
    picker.style.left = left + "px";
    picker.style.top = top + "px";
    const search = document.getElementById("emoji-search");
    search.value = "";
    filterEmojis("");
    requestAnimationFrame(function() { search.focus(); });
}

function closeEmojiPicker() {
    const picker = document.getElementById("emoji-picker");
    if (picker) picker.style.display = "none";
}

document.addEventListener("click", function(e) {
    const picker = document.getElementById("emoji-picker");
    const btn = document.getElementById("emoji-btn");
    if (picker?.style.display === "block"
        && !picker.contains(e.target)
        && !btn?.contains(e.target)) {
        closeEmojiPicker();
    }
});

