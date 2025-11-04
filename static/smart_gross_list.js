
document.getElementById('health-profile-form').addEventListener('submit', async (e) => {
    e.preventDefault();

    const form = e.target;
    const formData = {
        age: form.age.value,
        gender: form.gender.value,
        height: form.height.value,
        weight: form.weight.value,
        systolicBP: form.systolicBP.value,
        diastolicBP: form.diastolicBP.value,
        bloodSugar: form.bloodSugar.value,
        cholesterol: form.cholesterol.value,
        activityLevel: form.activityLevel.value,
        dietaryGoals: form.dietaryGoals.value,
        dietaryRestrictions: form.dietaryRestrictions.value,
        preferredCuisines: form.preferredCuisines.value,
        budgetLevel: form.budgetLevel.value,
        mealPlanDuration: form.mealPlanDuration.value,
        region: form.region.value,
        weather: form.weather.value
    };

    const resultsSection = document.getElementById('results-section');
    resultsSection.innerHTML = `
        <div class="card">
            <div class="card-content" style="text-align: center;">
                <p>⏳ Generating your personalized grocery list...</p>
            </div>
        </div>`;

    try {
        const response = await fetch('/api/generate_grocery_list', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(formData)
        });

        if (!response.ok) {
            throw new Error(`HTTP error! status: ${response.status}`);
        }

        const data = await response.json();

        let html = `
            <div class="card">
                <div class="card-header">
                    <h2 class="card-title">Your Personalized Grocery List</h2>
                </div>
                <div class="card-content">`;

        if (data.grocery_list && data.grocery_list.length > 0) {
            const categories = {};
            data.grocery_list.forEach(item => {
                if (!categories[item.category]) {
                    categories[item.category] = [];
                }
                categories[item.category].push(item);
            });

            for (const category in categories) {
                html += `<h3>${category}</h3><ul>`;
                categories[category].forEach(item => {
                    html += `<li><span class="item-name">${item.name}</span>: ${item.quantity}</li>`;
                });
                html += `</ul>`;
            }
        } else {
            html += '<p>Could not generate a grocery list at this time. Please try again.</p>';
        }

        html += '</div></div>';
        resultsSection.innerHTML = html;

    } catch (error) {
        resultsSection.innerHTML = `
            <div class="card">
                <div class="card-content" style="text-align: center; color: red;">
                    <p>❌ Error: ${error.message}</p>
                </div>
            </div>`;
    }
});
