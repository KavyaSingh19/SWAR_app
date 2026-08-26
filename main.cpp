#include <iostream>
#include <fstream>
#include <sstream>
#include <vector>
#include <string>

using namespace std;

// Data ko neatly store karne ke liye structure
struct Content {
    string category;
    string name;
    string mood;
    string weather;
};

// Strings ke aage-piche se extra spaces hatane ka function (taaki matching sahi ho)
string trim(const string& str) {
    size_t first = str.find_first_not_of(' ');
    if (string::npos == first) return str;
    size_t last = str.find_last_not_of(' ');
    return str.substr(first, (last - first + 1));
}

int main() {
    string userMood, userWeather;

    // 1. User se Terminal mein input lena (Baad mein Python directly input bhejega)
    cout << "Enter your Mood (Happy, Sad, Romantic, Motivated, Stressed): ";
    cin >> userMood;
    cout << "Enter current Weather (Sunny, Rainy, Cloudy): ";
    cin >> userWeather;

    // 2. content.txt file ko read mode mein open karna
    ifstream file("content.txt");
    if (!file.is_open()) {
        cout << "Error: Could not open content.txt file! Make sure it is in the same folder." << endl;
        return 1;
    }

    vector<Content> database;
    string line;

    // 3. File ko line-by-line read karna aur pipeline '|' ke basis par break karna
    while (getline(file, line)) {
        stringstream ss(line);
        string cat, nm, md, wt;

        if (getline(ss, cat, '|') && getline(ss, nm, '|') && getline(ss, md, '|') && getline(ss, wt, '|')) {
            Content item;
            item.category = trim(cat);
            item.name = trim(nm);
            item.mood = trim(md);
            item.weather = trim(wt);
            database.push_back(item); // Humare vectors list mein add karna
        }
    }
    file.close(); // Kaam khatam hone par file close karna zaroori hai

    // 4. Filtering and displaying the recommendations
    cout << "\n=== YOUR PERSONALIZED RECOMMENDATIONS ===\n" << endl;
    bool found = false;

    for (const auto& item : database) {
        // Agar user ka mood aur weather file ke tags se exact match hota hai
        if (item.mood == userMood && item.weather == userWeather) {
            cout << "- [" << item.category << "] " << item.name << endl;
            found = true;
        }
    }

    if (!found) {
        cout << "No specific recommendation found for this combo. Keep smiling anyway! :)" << endl;
    }

    cout << "\n=========================================" << endl;
    return 0;
}