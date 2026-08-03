console.log("Dashboard loaded successfully.");

if (typeof Chart !== "undefined") {
    Chart.defaults.font.family = "Inter, sans-serif";
    Chart.defaults.color = "#5F6F67";
    Chart.overrides.pie = Chart.overrides.pie || {};
    Chart.overrides.pie.plugins = Chart.overrides.pie.plugins || {};
}

const libraryPalette = ["#2E3B8C", "#F0A202", "#E5484D", "#1E9BC7", "#61637E", "#FFD873", "#4152AD", "#B8790A"];

function updateClock() {

    const now = new Date();

    const options = {
        weekday: "long",
        year: "numeric",
        month: "long",
        day: "numeric"
    };

    document.getElementById("currentDate").innerHTML =
        now.toLocaleDateString("en-US", options);

    document.getElementById("currentTime").innerHTML =
        now.toLocaleTimeString();
}

setInterval(updateClock, 1000);

updateClock();

// ===========================
// Animated Counters
// ===========================

function animateCounter(id){

    const counter = document.getElementById(id);

    if(!counter) return;

    const target = parseInt(counter.innerText);

    let current = 0;

    const increment = Math.max(1, Math.ceil(target / 50));

    const timer = setInterval(function(){

        current += increment;

        if(current >= target){

            counter.innerText = target;

            clearInterval(timer);

        }

        else{

            counter.innerText = current;

        }

    },20);

}

window.onload=function(){

    updateClock();

    animateCounter("booksCounter");
    animateCounter("copiesCounter");
    animateCounter("categoriesCounter");
    animateCounter("membersCounter");
    animateCounter("borrowedCounter");
    animateCounter("overdueCounter");

};

// ==========================
// CATEGORY PIE CHART
// ==========================

if (typeof categoryData !== "undefined") {

    new Chart(

        document.getElementById("categoryChart"),

        {

            type: "pie",

            data: {

                labels: categoryData.map(item => item[0]),

                datasets: [{
                    data: categoryData.map(item => item[1]),
                    backgroundColor: libraryPalette,
                    borderColor: "#F5FAF7",
                    borderWidth: 2
                }]

            },

            options: {

                responsive: true,

                plugins: {

                    legend: {

                        position: "bottom"

                    }

                }

            }

        }

    );

}


// ==========================
// BORROW STATUS BAR CHART
// ==========================

if (typeof borrowData !== "undefined") {

    new Chart(

        document.getElementById("borrowChart"),

        {

            type: "bar",

            data: {

                labels: borrowData.map(item => item[0]),

                datasets: [{

                    label: "Books",

                    data: borrowData.map(item => item[1]),
                    backgroundColor: "#2E3B8C",
                    borderRadius: 4

                }]

            },

            options: {

                responsive: true,

                plugins: {

                    legend: {

                        display: false

                    }

                },

                scales: {

                    y: {

                        beginAtZero: true

                    }

                }

            }

        }

    );

}