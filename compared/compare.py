import json
import math
import os
from datetime import datetime

import pandas as pd


class TrafficAnalysisComparator:
    def __init__(self, selenium_file, playwright_file):
        self.selenium_data = self.load_json(selenium_file)
        self.playwright_data = self.load_json(playwright_file)
        self.comparison_results = {}

    def load_json(self, file_path):
        """Load JSON data from file"""
        with open(file_path, "r", encoding="utf-8") as f:
            return json.load(f)

    def extract_location_data(self, data, source_name):
        """Extract and flatten location data from JSON structure"""
        locations = []

        for batch in data.get("batches", []):
            batch_num = batch.get("batch_number", 1)
            batch_processing_time = batch.get("processing_time", 0)

            # Handle both result structures (list vs dict with locations key)
            if "result" in batch:
                if isinstance(batch["result"], list):
                    batch_locations = batch["result"]
                elif (
                    isinstance(batch["result"], dict) and "locations" in batch["result"]
                ):
                    batch_locations = batch["result"]["locations"]
                else:
                    batch_locations = []

                for loc in batch_locations:
                    if loc:  # Ensure location data exists
                        # Extract day and time from screenshot path
                        screenshot_path = loc.get("screenshot_path", "")
                        day_time_info = self.extract_day_time_from_path(screenshot_path)

                        location_data = {
                            "source": source_name,
                            "batch_number": batch_num,
                            "batch_processing_time": batch_processing_time,
                            "coordinates": f"{loc.get('coordinates', {}).get('lat', 'N/A')}, {loc.get('coordinates', {}).get('lng', 'N/A')}",
                            "lat": loc.get("coordinates", {}).get("lat", 0),
                            "lng": loc.get("coordinates", {}).get("lng", 0),
                            "score": loc.get("score", 0),
                            "storefront_score": loc.get("storefront_score", 0),
                            "area_score": loc.get("area_score", 0),
                            "total_pixels_analyzed": loc.get(
                                "total_pixels_analyzed", 0
                            ),
                            "traffic_type": loc.get("traffic_type", "unknown"),
                            "method": loc.get("method", "unknown"),
                            "storefront_found": loc.get("storefront_details", {}).get(
                                "found", False
                            ),
                            "storefront_distance": loc.get(
                                "storefront_details", {}
                            ).get("distance", 0),
                            "storefront_color": loc.get("storefront_details", {}).get(
                                "color", "gray"
                            ),
                            "analysis_timestamp": loc.get("analysis_timestamp", 0),
                            # "screenshot_url": loc.get("screenshot_url", ""),
                            "day_of_week": day_time_info["day"],
                            "time_of_day": day_time_info["time"],
                            "time_category": day_time_info["category"],
                        }

                        # Add color distribution
                        color_dist = loc.get("color_distribution", {})
                        for color in ["dark_red", "red", "yellow", "green", "gray"]:
                            location_data[f"color_{color}"] = color_dist.get(color, 0)

                        # Add area details
                        area_details = loc.get("area_details", {})
                        for radius in ["50m", "100m", "150m"]:
                            area_data = area_details.get(radius, {})
                            location_data[f"area_{radius}_score"] = area_data.get(
                                "score", 0
                            )
                            location_data[f"area_{radius}_pixels"] = area_data.get(
                                "pixels", 0
                            )

                        locations.append(location_data)

        return locations

    def extract_day_time_from_path(self, screenshot_path):
        """Extract day of week and time from screenshot path"""
        import re

        # Default values
        day_time_info = {"day": "Unknown", "time": "Unknown", "category": "Unknown"}

        if not screenshot_path:
            return day_time_info

        # Extract filename
        filename = os.path.basename(screenshot_path)

        # Pattern to match day and time in filename
        # 24.7934_46.5934
        pattern = r"traffic_.*?_.*?_(.*?)_(.*?)_pinned"
        match = re.search(pattern, filename)

        if match:
            day_part = match.group(1)
            time_part = match.group(2)

            # # Map day names to standardized format
            # day_mapping = {
            #     "monday": "Monday",
            #     "tuesday": "Tuesday",
            #     "wednesday": "Wednesday",
            #     "thursday": "Thursday",
            #     "friday": "Friday",
            #     "saturday": "Saturday",
            #     "sunday": "Sunday",
            # }

            # # Standardize day name
            # day_lower = day_part.lower()
            # day_time_info["day"] = day_mapping.get(day_lower, day_part)

            day_time_info["day"] = day_part.capitalize()

            # Standardize time format
            time_part = (
                time_part.replace("-", ":").replace("AM", " AM").replace("PM", " PM")
            ).split("_")[-1]
            day_time_info["time"] = time_part

            # Categorize time
            if "AM" in time_part:
                hour = int(
                    time_part.split(":")[0]
                    if ":" in time_part
                    else time_part.split()[0]
                )
                if hour < 6:
                    day_time_info["category"] = "Early Morning"
                elif hour < 12:
                    day_time_info["category"] = "Morning"
            else:  # PM
                hour = int(
                    time_part.split(":")[0]
                    if ":" in time_part
                    else time_part.split()[0]
                )
                if hour == 12 or hour < 6:
                    day_time_info["category"] = "Afternoon"
                elif hour < 9:
                    day_time_info["category"] = "Evening"
                else:
                    day_time_info["category"] = "Night"

        return day_time_info

    def calculate_variation_metrics(self, selenium_loc, playwright_loc):
        """Calculate various variation metrics between Selenium and Playwright"""
        variation_metrics = {}

        # Score variations
        variation_metrics["score_absolute_difference"] = abs(
            playwright_loc["score"] - selenium_loc["score"]
        )
        variation_metrics["score_relative_difference"] = (
            (
                variation_metrics["score_absolute_difference"]
                / selenium_loc["score"]
                * 100
            )
            if selenium_loc["score"] > 0
            else 0
        )

        # Storefront detection variation
        variation_metrics["storefront_detection_variation"] = (
            1
            if selenium_loc["storefront_found"] != playwright_loc["storefront_found"]
            else 0
        )

        # Storefront distance variation
        variation_metrics["storefront_distance_difference"] = abs(
            selenium_loc["storefront_distance"] - playwright_loc["storefront_distance"]
        )

        # Area score variations
        for radius in ["50m", "100m", "150m"]:
            sel_area = selenium_loc.get(f"area_{radius}_score", 0)
            play_area = playwright_loc.get(f"area_{radius}_score", 0)
            variation_metrics[f"area_{radius}_absolute_difference"] = abs(
                play_area - sel_area
            )
            variation_metrics[f"area_{radius}_relative_difference"] = (
                (
                    variation_metrics[f"area_{radius}_absolute_difference"]
                    / sel_area
                    * 100
                )
                if sel_area > 0
                else 0
            )

        # Color distribution variations
        for color in ["dark_red", "red", "yellow", "green", "gray"]:
            sel_color = selenium_loc.get(f"color_{color}", 0)
            play_color = playwright_loc.get(f"color_{color}", 0)
            variation_metrics[f"color_{color}_absolute_difference"] = abs(
                play_color - sel_color
            )
            variation_metrics[f"color_{color}_relative_difference"] = (
                (
                    variation_metrics[f"color_{color}_absolute_difference"]
                    / sel_color
                    * 100
                )
                if sel_color > 0
                else 0
            )

        return variation_metrics

    def compare_locations(self):
        """Compare locations between Selenium and Playwright"""
        selenium_locations = self.extract_location_data(self.selenium_data, "Selenium")
        playwright_locations = self.extract_location_data(
            self.playwright_data, "Playwright"
        )

        # Create DataFrames
        # df_selenium = pd.DataFrame(selenium_locations)
        # df_playwright = pd.DataFrame(playwright_locations)

        # Merge on coordinates for comparison
        comparison_data = []
        variation_data = []

        for idx, sel_loc in enumerate(selenium_locations):
            # Find matching Playwright location by coordinates
            matching_playwright = None
            for play_loc in playwright_locations:
                if (
                    abs(sel_loc["lat"] - play_loc["lat"]) < 0.0001
                    and abs(sel_loc["lng"] - play_loc["lng"]) < 0.0001
                ):
                    matching_playwright = play_loc
                    break

            if matching_playwright:
                # Calculate variation metrics
                variation_metrics = self.calculate_variation_metrics(
                    sel_loc, matching_playwright
                )

                comparison = {
                    "coordinates": sel_loc["coordinates"],
                    "lat": sel_loc["lat"],
                    "lng": sel_loc["lng"],
                    "traffic_type_selenium": sel_loc["traffic_type"],
                    "traffic_type_playwright": matching_playwright["traffic_type"],
                    "day_of_week": sel_loc["day_of_week"],
                    "time_of_day": sel_loc["time_of_day"],
                    "time_category": sel_loc["time_category"],
                    # Scores comparison - Playwright vs Selenium
                    "score_selenium": sel_loc["score"],
                    "score_playwright": matching_playwright["score"],
                    "score_difference": matching_playwright["score"]
                    - sel_loc["score"],  # Positive = improvement
                    "score_improvement_pct": (
                        (
                            (matching_playwright["score"] - sel_loc["score"])
                            / sel_loc["score"]
                            * 100
                        )
                        if sel_loc["score"] > 0
                        else 0
                    ),
                    # Storefront scores
                    "storefront_score_selenium": sel_loc["storefront_score"],
                    "storefront_score_playwright": matching_playwright[
                        "storefront_score"
                    ],
                    "storefront_found_selenium": sel_loc["storefront_found"],
                    "storefront_found_playwright": matching_playwright[
                        "storefront_found"
                    ],
                    # Area scores
                    "area_score_selenium": sel_loc["area_score"],
                    "area_score_playwright": matching_playwright["area_score"],
                    # Pixel analysis
                    "pixels_selenium": sel_loc["total_pixels_analyzed"],
                    "pixels_playwright": matching_playwright["total_pixels_analyzed"],
                    # Storefront details
                    "storefront_distance_selenium": sel_loc["storefront_distance"],
                    "storefront_distance_playwright": matching_playwright[
                        "storefront_distance"
                    ],
                    "storefront_color_selenium": sel_loc["storefront_color"],
                    "storefront_color_playwright": matching_playwright[
                        "storefront_color"
                    ],
                    # Screenshot URLs
                    # "screenshot_selenium": sel_loc["screenshot_url"],
                    # "screenshot_playwright": matching_playwright["screenshot_url"],
                    # Variation metrics
                    **variation_metrics,
                }
                comparison_data.append(comparison)

                # Collect variation data for summary
                variation_data.append(variation_metrics)

        self.comparison_df = pd.DataFrame(comparison_data)
        self.variation_df = pd.DataFrame(variation_data)

        # Create filtered data for analysis
        self.typical_comparison_df = self.comparison_df[
            self.comparison_df["traffic_type_selenium"] == "typical"
        ].copy()
        self.live_comparison_df = self.comparison_df[
            self.comparison_df["traffic_type_selenium"] == "live"
        ].copy()

        return self.comparison_df

    def generate_time_analysis(self):
        """Generate time-based analysis"""
        if self.comparison_df.empty:
            return {}

        time_analysis = {}

        # Processing time comparison
        selenium_total_time = self.selenium_data.get("total_processing_time_seconds", 0)
        playwright_total_time = self.playwright_data.get(
            "total_processing_time_seconds", 0
        )
        time_difference = playwright_total_time - selenium_total_time
        time_difference_pct = (
            (time_difference / selenium_total_time * 100)
            if selenium_total_time > 0
            else 0
        )

        time_analysis.update(
            {
                "selenium_total_processing_time": selenium_total_time,
                "playwright_total_processing_time": playwright_total_time,
                "processing_time_difference": time_difference,
                "processing_time_difference_pct": time_difference_pct,
                "processing_time_comparison": (
                    "Faster"
                    if time_difference < 0
                    else "Slower" if time_difference > 0 else "Same"
                ),
            }
        )

        # Time of day analysis
        time_categories = self.comparison_df["time_category"].value_counts()
        time_analysis["time_category_distribution"] = time_categories.to_dict()

        # Day of week analysis
        day_distribution = self.comparison_df["day_of_week"].value_counts()
        time_analysis["day_distribution"] = day_distribution.to_dict()

        # Performance by time category
        performance_by_time = (
            self.comparison_df.groupby("time_category")
            .agg(
                {
                    "score_difference": "mean",
                    "score_relative_difference": "mean",
                    "score_selenium": "mean",
                    "score_playwright": "mean",
                }
            )
            .round(2)
        )
        time_analysis["performance_by_time_category"] = performance_by_time.to_dict()

        # Performance by day of week
        performance_by_day = (
            self.comparison_df.groupby("day_of_week")
            .agg(
                {
                    "score_difference": "mean",
                    "score_relative_difference": "mean",
                    "score_selenium": "mean",
                    "score_playwright": "mean",
                }
            )
            .round(2)
        )
        time_analysis["performance_by_day"] = performance_by_day.to_dict()

        return time_analysis

    def generate_traffic_type_analysis(self):
        """Generate detailed traffic type analysis"""
        if self.comparison_df.empty:
            return {}

        traffic_analysis = {}

        # Traffic type distribution
        selenium_traffic = self.comparison_df["traffic_type_selenium"].value_counts()
        playwright_traffic = self.comparison_df[
            "traffic_type_playwright"
        ].value_counts()

        traffic_analysis.update(
            {
                "selenium_traffic_distribution": selenium_traffic.to_dict(),
                "playwright_traffic_distribution": playwright_traffic.to_dict(),
                "traffic_type_consistency": (
                    self.comparison_df["traffic_type_selenium"]
                    == self.comparison_df["traffic_type_playwright"]
                ).mean()
                * 100,
            }
        )

        # Performance by traffic type
        for traffic_type in ["typical", "live"]:
            traffic_data = self.comparison_df[
                (self.comparison_df["traffic_type_selenium"] == traffic_type)
                & (self.comparison_df["traffic_type_playwright"] == traffic_type)
            ]

            if len(traffic_data) > 0:
                traffic_analysis[f"{traffic_type}_locations_count"] = len(traffic_data)
                traffic_analysis[f"{traffic_type}_avg_score_selenium"] = traffic_data[
                    "score_selenium"
                ].mean()
                traffic_analysis[f"{traffic_type}_avg_score_playwright"] = traffic_data[
                    "score_playwright"
                ].mean()
                traffic_analysis[f"{traffic_type}_score_difference"] = traffic_data[
                    "score_difference"
                ].mean()
                traffic_analysis[f"{traffic_type}_score_difference_pct"] = traffic_data[
                    "score_improvement_pct"
                ].mean()

        # Traffic type mismatches
        mismatches = self.comparison_df[
            self.comparison_df["traffic_type_selenium"]
            != self.comparison_df["traffic_type_playwright"]
        ]
        traffic_analysis["traffic_type_mismatches_count"] = len(mismatches)
        traffic_analysis["traffic_type_mismatches_pct"] = (
            len(mismatches) / len(self.comparison_df)
        ) * 100

        if len(mismatches) > 0:
            traffic_analysis["mismatch_details"] = (
                mismatches[["traffic_type_selenium", "traffic_type_playwright"]]
                .value_counts()
                .to_dict()
            )

        return traffic_analysis

    def generate_variation_summary(self):
        """Generate comprehensive variation analysis summary"""
        if self.variation_df.empty:
            return {}

        variation_summary = {
            # Overall variation metrics
            "mean_absolute_difference_score": self.variation_df[
                "score_absolute_difference"
            ].mean(),
            "mean_relative_difference_score": self.variation_df[
                "score_relative_difference"
            ].mean(),
            "max_absolute_difference_score": self.variation_df[
                "score_absolute_difference"
            ].max(),
            "max_relative_difference_score": self.variation_df[
                "score_relative_difference"
            ].max(),
            # Storefront detection variations
            "storefront_detection_variation_rate": self.variation_df[
                "storefront_detection_variation"
            ].mean()
            * 100,
            "total_storefront_detection_variations": self.variation_df[
                "storefront_detection_variation"
            ].sum(),
            # Storefront distance variations
            "mean_storefront_distance_difference": self.variation_df[
                "storefront_distance_difference"
            ].mean(),
            "max_storefront_distance_difference": self.variation_df[
                "storefront_distance_difference"
            ].max(),
            # Area score variations
            "mean_absolute_difference_area_50m": self.variation_df[
                "area_50m_absolute_difference"
            ].mean(),
            "mean_absolute_difference_area_100m": self.variation_df[
                "area_100m_absolute_difference"
            ].mean(),
            "mean_absolute_difference_area_150m": self.variation_df[
                "area_150m_absolute_difference"
            ].mean(),
            # Color distribution variations
            "mean_absolute_difference_color_green": self.variation_df[
                "color_green_absolute_difference"
            ].mean(),
            "mean_absolute_difference_color_yellow": self.variation_df[
                "color_yellow_absolute_difference"
            ].mean(),
            "mean_absolute_difference_color_red": self.variation_df[
                "color_red_absolute_difference"
            ].mean(),
            "mean_absolute_difference_color_dark_red": self.variation_df[
                "color_dark_red_absolute_difference"
            ].mean(),
            "mean_absolute_difference_color_gray": self.variation_df[
                "color_gray_absolute_difference"
            ].mean(),
            # Variation distribution
            "low_variation_locations": len(
                self.variation_df[self.variation_df["score_relative_difference"] < 10]
            ),
            "medium_variation_locations": len(
                self.variation_df[
                    (self.variation_df["score_relative_difference"] >= 10)
                    & (self.variation_df["score_relative_difference"] < 25)
                ]
            ),
            "high_variation_locations": len(
                self.variation_df[self.variation_df["score_relative_difference"] >= 25]
            ),
            # Consistency metrics
            "consistency_score_based": 100
            - self.variation_df["score_relative_difference"].mean(),
            "consistency_storefront_detection": 100
            - (self.variation_df["storefront_detection_variation"].mean() * 100),
        }

        return variation_summary

    def generate_summary_stats(self):
        """Generate comprehensive summary statistics"""
        if self.comparison_df.empty:
            return {}

        variation_summary = self.generate_variation_summary()
        time_analysis = self.generate_time_analysis()
        traffic_analysis = self.generate_traffic_type_analysis()

        # Calculate typical traffic statistics
        typical_locations = len(self.typical_comparison_df)
        typical_improvement = (
            self.typical_comparison_df["score_difference"].mean()
            if typical_locations > 0
            else 0
        )
        typical_improvement_pct = (
            self.typical_comparison_df["score_improvement_pct"].mean()
            if typical_locations > 0
            else 0
        )

        summary = {
            "total_locations_compared": len(self.comparison_df),
            "comparison_date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            # Score statistics - Playwright vs Selenium
            "avg_score_selenium": self.comparison_df["score_selenium"].mean(),
            "avg_score_playwright": self.comparison_df["score_playwright"].mean(),
            "avg_score_improvement": self.comparison_df["score_difference"].mean(),
            "avg_score_improvement_pct": self.comparison_df[
                "score_improvement_pct"
            ].mean(),
            # Storefront detection
            "storefront_detected_selenium": self.comparison_df[
                "storefront_found_selenium"
            ].sum(),
            "storefront_detected_playwright": self.comparison_df[
                "storefront_found_playwright"
            ].sum(),
            "storefront_detection_improvement": self.comparison_df[
                "storefront_found_playwright"
            ].sum()
            - self.comparison_df["storefront_found_selenium"].sum(),
            # Performance metrics
            "locations_with_improvement": len(
                self.comparison_df[self.comparison_df["score_difference"] > 0]
            ),
            "locations_with_degradation": len(
                self.comparison_df[self.comparison_df["score_difference"] < 0]
            ),
            "locations_unchanged": len(
                self.comparison_df[self.comparison_df["score_difference"] == 0]
            ),
            # Best improvements
            "max_improvement": self.comparison_df["score_difference"].max(),
            "max_improvement_pct": self.comparison_df["score_improvement_pct"].max(),
            # Traffic type breakdown
            "typical_locations_count": typical_locations,
            "typical_improvement": typical_improvement,
            "typical_improvement_pct": typical_improvement_pct,
            "live_locations_count": len(
                self.comparison_df[
                    self.comparison_df["traffic_type_selenium"] == "live"
                ]
            ),
            # Variation metrics
            **variation_summary,
            # Time analysis
            **time_analysis,
            # Traffic type analysis
            **traffic_analysis,
        }

        return summary

    def generate_pagination_script(self, total_pages, items_per_page=10):
        """Generate JavaScript for pagination"""
        return f"""
        <script>
            let currentPage = 1;
            const itemsPerPage = {items_per_page};
            const totalPages = {total_pages};
            
            function showPage(page) {{
                currentPage = page;
                const rows = document.querySelectorAll('#locationsTable tbody tr');
                const startIndex = (page - 1) * itemsPerPage;
                const endIndex = startIndex + itemsPerPage;
                
                rows.forEach((row, index) => {{
                    if (index >= startIndex && index < endIndex) {{
                        row.style.display = '';
                    }} else {{
                        row.style.display = 'none';
                    }}
                }});
                
                updatePaginationButtons();
                updatePageInfo();
            }}
            
            function updatePaginationButtons() {{
                document.getElementById('prevBtn').disabled = currentPage === 1;
                document.getElementById('nextBtn').disabled = currentPage === totalPages;
                
                // Update active page button
                document.querySelectorAll('.page-btn').forEach(btn => {{
                    btn.classList.remove('active');
                    if (parseInt(btn.textContent) === currentPage) {{
                        btn.classList.add('active');
                    }}
                }});
            }}
            
            function updatePageInfo() {{
                document.getElementById('pageInfo').textContent = `Page ${{currentPage}} of ${{totalPages}}`;
            }}
            
            function nextPage() {{
                if (currentPage < totalPages) {{
                    showPage(currentPage + 1);
                }}
            }}
            
            function prevPage() {{
                if (currentPage > 1) {{
                    showPage(currentPage - 1);
                }}
            }}
            
            // Initialize pagination
            document.addEventListener('DOMContentLoaded', function() {{
                showPage(1);
            }});
        </script>
        """

    def generate_pagination_controls(self, total_pages, current_page=1):
        """Generate HTML for pagination controls"""
        pages_html = '<div class="pagination-controls">'
        pages_html += (
            f'<span id="pageInfo" class="page-info">Page 1 of {total_pages}</span>'
        )
        pages_html += '<div class="pagination-buttons">'
        pages_html += '<button id="prevBtn" class="page-nav" onclick="prevPage()">‹ Previous</button>'

        # Show page numbers (max 7 pages visible)
        start_page = max(1, current_page - 3)
        end_page = min(total_pages, start_page + 6)

        for page in range(1, total_pages + 1):
            if (
                page == 1
                or page == total_pages
                or (page >= start_page and page <= end_page)
            ):
                active_class = "active" if page == current_page else ""
                pages_html += f'<button class="page-btn {active_class}" onclick="showPage({page})">{page}</button>'
            elif page == start_page - 1 or page == end_page + 1:
                pages_html += '<span class="page-ellipsis">...</span>'

        pages_html += (
            '<button id="nextBtn" class="page-nav" onclick="nextPage()">Next ›</button>'
        )
        pages_html += "</div></div>"

        return pages_html

    def get_trend_arrow(self, value, threshold=0.1):
        """Get trend arrow based on value difference"""
        if value > threshold:
            return "🟢 ↑"  # Significant improvement
        elif value < -threshold:
            return "🔴 ↓"  # Significant degradation
        elif value > 0:
            return "↗️"  # Slight improvement
        elif value < 0:
            return "↘️"  # Slight degradation
        else:
            return "➡️"  # No change

    def generate_html_report(self, output_file="traffic_comparison_report.html"):
        """Generate comprehensive HTML report with all comparisons"""
        if self.comparison_df.empty:
            print("No comparison data available. Run compare_locations() first.")
            return

        summary = self.generate_summary_stats()

        # Calculate pagination
        items_per_page = 10
        total_pages = math.ceil(len(self.comparison_df) / items_per_page)

        # Create HTML content
        html_content = f"""
        <!DOCTYPE html>
        <html lang="en">
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>Google Maps Traffic Analysis Comparison Report</title>
            <style>
                body {{ font-family: 'Arial', 'Segoe UI', Tahoma, sans-serif; margin: 20px; background-color: #f5f5f5; }}
                .container {{ max-width: 1400px; margin: 0 auto; background: white; padding: 20px; border-radius: 10px; box-shadow: 0 2px 10px rgba(0,0,0,0.1); }}
                .header {{ text-align: center; background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; padding: 20px; border-radius: 8px; margin-bottom: 20px; }}
                .summary {{ background: #f8f9fa; padding: 20px; border-radius: 8px; margin-bottom: 20px; }}
                .metric-card {{ background: white; padding: 15px; margin: 10px; border-radius: 8px; box-shadow: 0 2px 5px rgba(0,0,0,0.1); display: inline-block; width: calc(25% - 40px); min-width: 200px; text-align: center; }}
                .metric-value {{ font-size: 24px; font-weight: bold; color: #333; }}
                .metric-label {{ font-size: 14px; color: #666; }}
                .improvement-positive {{ color: #28a745; }}
                .improvement-negative {{ color: #dc3545; }}
                .variation-high {{ color: #dc3545; background-color: #ffe6e6; }}
                .variation-medium {{ color: #ffc107; background-color: #fff9e6; }}
                .variation-low {{ color: #28a745; background-color: #e6ffe6; }}
                table {{ width: 100%; border-collapse: collapse; margin: 20px 0; }}
                th, td {{ padding: 12px; text-align: left; border-bottom: 1px solid #ddd; }}
                th {{ background-color: #f8f9fa; font-weight: bold; text-align: center; }}
                tr:hover {{ background-color: #f5f5f5; }}
                .screenshot-cell {{ max-width: 200px; }}
                .screenshot-img {{ max-width: 150px; max-height: 100px; border: 1px solid #ddd; border-radius: 4px; }}
                .section-title {{ background: #e9ecef; padding: 15px; border-radius: 8px; margin: 30px 0 15px 0; border-left: 5px solid #667eea; }}
                .variation-metrics {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(250px, 1fr)); gap: 15px; margin: 20px 0; }}
                .variation-metric-card {{ background: white; padding: 15px; border-radius: 8px; box-shadow: 0 2px 5px rgba(0,0,0,0.1); border-left: 4px solid #6c757d; }}
                .pagination-controls {{ display: flex; justify-content: space-between; align-items: center; margin: 20px 0; padding: 10px; background: #f8f9fa; border-radius: 8px; }}
                .pagination-buttons {{ display: flex; gap: 5px; }}
                .page-btn, .page-nav {{ padding: 8px 12px; border: 1px solid #ddd; background: white; cursor: pointer; border-radius: 4px; }}
                .page-btn.active {{ background: #667eea; color: white; border-color: #667eea; }}
                .page-btn:hover, .page-nav:hover {{ background: #e9ecef; }}
                .page-nav:disabled {{ background: #f8f9fa; color: #6c757d; cursor: not-allowed; }}
                .page-info {{ font-weight: bold; color: #495057; }}
                .traffic-badge {{ padding: 4px 8px; border-radius: 12px; font-size: 12px; font-weight: bold; }}
                .traffic-typical {{ background: #d4edda; color: #155724; }}
                .traffic-live {{ background: #f8d7da; color: #721c24; }}
                .trend-arrow {{ font-size: 16px; margin-right: 5px; }}
                .page-ellipsis {{ padding: 8px 4px; color: #6c757d; }}
                .time-badge {{ padding: 4px 8px; border-radius: 12px; font-size: 11px; font-weight: bold; background: #e9ecef; color: #495057; }}
                .analysis-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 20px; margin: 20px 0; }}
                .analysis-card {{ background: white; padding: 20px; border-radius: 8px; box-shadow: 0 2px 5px rgba(0,0,0,0.1); }}
            </style>
        </head>
        <body>
            <div class="container">
                <div class="header">
                    <h1>🚗 Google Maps Traffic Analysis Comparison Report</h1>
                    <h3>🎯 Playwright vs Selenium</h3>
                    <p>Generated on: {summary['comparison_date']}</p>
                </div>
                
                <div class="section-title">
                    <h2>📊 Performance Summary & Differences</h2>
                </div>
                
                <div class="summary">
                    <div class="metric-card">
                        <div class="metric-value">{summary['total_locations_compared']}</div>
                        <div class="metric-label">Locations Compared</div>
                    </div>
                    <div class="metric-card">
                        <div class="metric-value { 'improvement-positive' if summary['avg_score_improvement'] > 0 else 'improvement-negative' }">
                            {self.get_trend_arrow(summary['avg_score_improvement'])} {summary['avg_score_improvement']:.2f}
                        </div>
                        <div class="metric-label">Average Score Difference</div>
                    </div>
                    <div class="metric-card">
                        <div class="metric-value { 'improvement-positive' if summary['processing_time_difference'] < 0 else 'improvement-negative' }">
                            {self.get_trend_arrow(-summary['processing_time_difference']/100)} {abs(summary['processing_time_difference']):.1f}s
                        </div>
                        <div class="metric-label">Processing Time Difference</div>
                    </div>
                    <div class="metric-card">
                        <div class="metric-value { 'improvement-positive' if summary['storefront_detection_improvement'] > 0 else 'improvement-negative' }">
                            {self.get_trend_arrow(summary['storefront_detection_improvement'])} {summary['storefront_detection_improvement']}
                        </div>
                        <div class="metric-label">Storefront Detection Difference</div>
                    </div>
                    <div class="metric-card">
                        <div class="metric-value improvement-positive">
                            {self.get_trend_arrow(1)} {summary['locations_with_improvement']}
                        </div>
                        <div class="metric-label">Locations with Higher Scores</div>
                    </div>
                    <div class="metric-card">
                        <div class="metric-value improvement-negative">
                            {self.get_trend_arrow(-1)} {summary['locations_with_degradation']}
                        </div>
                        <div class="metric-label">Locations with Lower Scores</div>
                    </div>
                    <div class="metric-card">
                        <div class="metric-value { 'variation-low' if summary['mean_relative_difference_score'] < 10 else 'variation-medium' if summary['mean_relative_difference_score'] < 25 else 'variation-high' }">
                            {summary['mean_relative_difference_score']:.1f}%
                        </div>
                        <div class="metric-label">Average Score Variation</div>
                    </div>
                    <div class="metric-card">
                        <div class="metric-value { 'variation-low' if summary['consistency_score_based'] > 90 else 'variation-medium' if summary['consistency_score_based'] > 75 else 'variation-high' }">
                            {summary['consistency_score_based']:.1f}%
                        </div>
                        <div class="metric-label">Score Consistency</div>
                    </div>
                </div>

                <div class="section-title">
                    <h2>⏱️ Processing Time Comparison</h2>
                </div>
                
                <div class="analysis-grid">
                    <div class="analysis-card">
                        <h3>Total Processing Time</h3>
                        <div class="metric-value">{summary['selenium_total_processing_time']:.1f}s</div>
                        <div class="metric-label">Selenium</div>
                    </div>
                    <div class="analysis-card">
                        <h3>Total Processing Time</h3>
                        <div class="metric-value { 'improvement-positive' if summary['processing_time_difference'] < 0 else 'improvement-negative' }">
                            {summary['playwright_total_processing_time']:.1f}s
                        </div>
                        <div class="metric-label">Playwright</div>
                    </div>
                    <div class="analysis-card">
                        <h3>Time Difference</h3>
                        <div class="metric-value { 'improvement-positive' if summary['processing_time_difference'] < 0 else 'improvement-negative' }">
                            {self.get_trend_arrow(-summary['processing_time_difference']/100)} {abs(summary['processing_time_difference']):.1f}s
                        </div>
                        <div class="metric-label">{summary['processing_time_comparison']} by {abs(summary['processing_time_difference_pct']):.1f}%</div>
                    </div>
                </div>

                <div class="section-title">
                    <h2>🚦 Traffic Type Analysis</h2>
                </div>
                
                <div class="analysis-grid">
                    <div class="analysis-card">
                        <h3>Traffic Type Distribution</h3>
                        <p><strong>Selenium:</strong> Typical: {summary['selenium_traffic_distribution'].get('typical', 0)}, Live: {summary['selenium_traffic_distribution'].get('live', 0)}</p>
                        <p><strong>Playwright:</strong> Typical: {summary['playwright_traffic_distribution'].get('typical', 0)}, Live: {summary['playwright_traffic_distribution'].get('live', 0)}</p>
                        <p><strong>Consistency:</strong> {summary['traffic_type_consistency']:.1f}%</p>
                    </div>
                    <div class="analysis-card">
                        <h3>Typical Traffic Performance</h3>
                        <p><strong>Selenium Score:</strong> {summary.get('typical_avg_score_selenium', 0):.2f}</p>
                        <p><strong>Playwright Score:</strong> {summary.get('typical_avg_score_playwright', 0):.2f}</p>
                        <p><strong>Difference:</strong> <span class="{ 'improvement-positive' if summary.get('typical_score_difference', 0) > 0 else 'improvement-negative' }">
                            {self.get_trend_arrow(summary.get('typical_score_difference', 0))} {summary.get('typical_score_difference', 0):.2f}
                        </span></p>
                    </div>
                    <div class="analysis-card">
                        <h3>Traffic Type Mismatches</h3>
                        <p><strong>Mismatches:</strong> {summary['traffic_type_mismatches_count']} locations</p>
                        <p><strong>Percentage:</strong> {summary['traffic_type_mismatches_pct']:.1f}%</p>
                        <p><strong>Details:</strong> {', '.join([f'{k[0]}→{k[1]} ({v})' for k, v in summary.get('mismatch_details', {}).items()]) if summary.get('mismatch_details') else 'None'}</p>
                    </div>
                </div>

                <div class="section-title">
                    <h2>📅 Time & Day Analysis</h2>
                </div>
                
                <div class="analysis-grid">
                    <div class="analysis-card">
                        <h3>Performance by Time of Day</h3>
                        {"".join([f"<p><strong>{category}:</strong> Diff: {summary['performance_by_time_category']['score_difference'].get(category, 0):.2f}, Var: {summary['performance_by_time_category']['score_relative_difference'].get(category, 0):.1f}%</p>" 
                                 for category in summary.get('time_category_distribution', {}).keys()])}
                    </div>
                    <div class="analysis-card">
                        <h3>Performance by Day of Week</h3>
                        {"".join([f"<p><strong>{day}:</strong> Diff: {summary['performance_by_day']['score_difference'].get(day, 0):.2f}, Var: {summary['performance_by_day']['score_relative_difference'].get(day, 0):.1f}%</p>" 
                                 for day in summary.get('day_distribution', {}).keys()])}
                    </div>
                    <div class="analysis-card">
                        <h3>Time Distribution</h3>
                        <p><strong>Time Categories:</strong> {', '.join([f'{k} ({v})' for k, v in summary.get('time_category_distribution', {}).items()])}</p>
                        <p><strong>Days of Week:</strong> {', '.join([f'{k} ({v})' for k, v in summary.get('day_distribution', {}).items()])}</p>
                    </div>
                </div>

                <div class="section-title">
                    <h2>📈 Score Variation Analysis</h2>
                </div>
                
                <div class="variation-metrics">
                    <div class="variation-metric-card">
                        <div class="metric-value">{summary['mean_absolute_difference_score']:.2f}</div>
                        <div class="metric-label">Mean Absolute Difference in Scores</div>
                    </div>
                    <div class="variation-metric-card">
                        <div class="metric-value">{summary['storefront_detection_variation_rate']:.1f}%</div>
                        <div class="metric-label">Storefront Detection Variation Rate</div>
                    </div>
                    <div class="variation-metric-card">
                        <div class="metric-value">{summary['mean_storefront_distance_difference']:.1f}</div>
                        <div class="metric-label">Mean Distance Difference</div>
                    </div>
                    <div class="variation-metric-card">
                        <div class="metric-value">{summary['consistency_storefront_detection']:.1f}%</div>
                        <div class="metric-label">Storefront Detection Consistency</div>
                    </div>
                </div>

                <div class="variation-metrics">
                    <div class="variation-metric-card">
                        <div class="metric-value variation-low">{summary['low_variation_locations']}</div>
                        <div class="metric-label">Low Variation Locations (&lt;10%)</div>
                    </div>
                    <div class="variation-metric-card">
                        <div class="metric-value variation-medium">{summary['medium_variation_locations']}</div>
                        <div class="metric-label">Medium Variation Locations (10-25%)</div>
                    </div>
                    <div class="variation-metric-card">
                        <div class="metric-value variation-high">{summary['high_variation_locations']}</div>
                        <div class="metric-label">High Variation Locations (&ge;25%)</div>
                    </div>
                </div>
                
                <div class="section-title">
                    <h2>🔍 Detailed Location Comparison</h2>
                </div>
                
                {self.generate_pagination_controls(total_pages)}
                
                <table id="locationsTable">
                    <thead>
                        <tr>
                            <th>Coordinates</th>
                            <th>Day & Time</th>
                            <th>Traffic Type <br>(S/P)</th>
                            <th>Selenium Score</th>
                            <th>Playwright Score</th>
                            <th>Difference</th>
                            <th>Difference <br>%</th>
                            <th>Storefront Found <br>(S/P)</th>
                            <th>Score Variation</th>
                        </tr>
                    </thead>
                    <tbody>
        """

        # Add table rows
        for _, row in self.comparison_df.iterrows():
            improvement_class = (
                "improvement-positive"
                if row["score_difference"] > 0
                else "improvement-negative" if row["score_difference"] < 0 else ""
            )
            variation_class = (
                "variation-low"
                if row["score_relative_difference"] < 10
                else (
                    "variation-medium"
                    if row["score_relative_difference"] < 25
                    else "variation-high"
                )
            )
            traffic_selenium_class = (
                "traffic-typical"
                if row["traffic_type_selenium"] == "typical"
                else "traffic-live"
            )
            traffic_playwright_class = (
                "traffic-typical"
                if row["traffic_type_playwright"] == "typical"
                else "traffic-live"
            )

            html_content += f"""
                        <tr>
                            <td>{row['coordinates']}</td>
                            <td>
                                <div>{row['day_of_week']}</div>
                                <div class="time-badge">{row['time_of_day']} ({row['time_category']})</div>
                            </td>
                            <td>
                                <span class="traffic-badge {traffic_selenium_class}">{row['traffic_type_selenium'][0].upper()}</span> / 
                                <span class="traffic-badge {traffic_playwright_class}">{row['traffic_type_playwright'][0].upper()}</span>
                            </td>
                            <td>{row['score_selenium']:.2f}</td>
                            <td>{row['score_playwright']:.2f}</td>
                            <td class="{improvement_class}">{self.get_trend_arrow(row['score_difference'])} {row['score_difference']:.2f}</td>
                            <td class="{improvement_class}">{self.get_trend_arrow(row['score_improvement_pct']/100)} {row['score_improvement_pct']:.1f}%</td>
                            <td>{'✅' if row['storefront_found_selenium'] else '❌'} / {'✅' if row['storefront_found_playwright'] else '❌'}</td>
                            <td class="{variation_class}">{row['score_relative_difference']:.1f}%</td>
                        </tr>
            """

        html_content += """
                    </tbody>
                </table>
                {generate_pagination_controls}
                <div style="margin-top: 30px; padding: 20px; background: #f8f9fa; border-radius: 8px;">
                    <h3>🎯 Key Findings & Observations</h3>
                    <ul>
                        <li>Playwright showed higher scores in <strong>{improved_locations}</strong> out of <strong>{total_locations}</strong> locations</li>
                        <li>Processing time: Playwright is <strong>{time_comparison}</strong> by <strong>{time_diff_abs:.1f}s ({time_diff_pct_abs:.1f}%)</strong></li>
                        <li>Maximum score difference: <strong>{max_imp:.2f}</strong> points</li>
                        <li>Storefront detection differed in <strong>{store_imp}</strong> locations</li>
                        <li>Traffic type consistency: <strong>{traffic_consistency:.1f}%</strong></li>
                        <li>Average score variation: <strong>{mean_variation_pct:.1f}%</strong></li>
                        <li>Overall consistency: <strong>{overall_consistency:.1f}%</strong></li>
                    </ul>
                </div>
            </div>
            {generate_pagination_script}
        </body>
        </html>
        """.format(
            generate_pagination_controls=self.generate_pagination_controls(total_pages),
            generate_pagination_script=self.generate_pagination_script(
                total_pages, items_per_page
            ),
            improved_locations=summary["locations_with_improvement"],
            total_locations=summary["total_locations_compared"],
            time_comparison=summary["processing_time_comparison"].lower(),
            time_diff_abs=abs(summary["processing_time_difference"]),
            time_diff_pct_abs=abs(summary["processing_time_difference_pct"]),
            max_imp=summary["max_improvement"],
            store_imp=summary["storefront_detection_improvement"],
            traffic_consistency=summary["traffic_type_consistency"],
            mean_variation_pct=summary["mean_relative_difference_score"],
            overall_consistency=summary["consistency_score_based"],
        )

        # Write HTML file
        with open(output_file, "w", encoding="utf-8") as f:
            f.write(html_content)

        print(f"HTML report generated: {output_file}")

    # def generate_csv_report(self, output_file="traffic_comparison_report.csv"):
    #     """Generate detailed CSV report"""
    #     if self.comparison_df.empty:
    #         print("No comparison data available. Run compare_locations() first.")
    #         return

    #     # Create enhanced CSV with all comparison data
    #     csv_df = self.comparison_df.copy()

    #     # Add additional calculated columns
    #     csv_df["score_difference_category"] = csv_df["score_difference"].apply(
    #         lambda x: (
    #             "High Improvement"
    #             if x > 10
    #             else (
    #                 "Medium Improvement"
    #                 if x > 5
    #                 else (
    #                     "Low Improvement"
    #                     if x > 0
    #                     else "No Change" if x == 0 else "Lower Score"
    #                 )
    #             )
    #         )
    #     )

    #     csv_df["storefront_detection_change"] = csv_df.apply(
    #         lambda row: (
    #             "Better"
    #             if row["storefront_found_playwright"]
    #             and not row["storefront_found_selenium"]
    #             else (
    #                 "Worse"
    #                 if not row["storefront_found_playwright"]
    #                 and row["storefront_found_selenium"]
    #                 else "Same"
    #             )
    #         ),
    #         axis=1,
    #     )

    #     csv_df["variation_severity"] = csv_df["score_relative_difference"].apply(
    #         lambda x: (
    #             "Low Variation"
    #             if x < 10
    #             else "Medium Variation" if x < 25 else "High Variation"
    #         )
    #     )

    #     csv_df["traffic_type_match"] = (
    #         csv_df["traffic_type_selenium"] == csv_df["traffic_type_playwright"]
    #     )
    #     csv_df["trend_direction"] = csv_df["score_difference"].apply(
    #         lambda x: self.get_trend_arrow(x)
    #     )

    #     # Save to CSV
    #     csv_df.to_csv(output_file, index=False, encoding="utf-8")
    #     print(f"CSV report generated: {output_file}")

    #     # Also generate a summary CSV
    #     summary_data = self.generate_summary_stats()
    #     summary_df = pd.DataFrame([summary_data])
    #     summary_csv_file = output_file.replace(".csv", "_summary.csv")
    #     summary_df.to_csv(summary_csv_file, index=False)
    #     print(f"Summary CSV generated: {summary_csv_file}")

    #     # Generate variation analysis CSV
    #     variation_csv_file = output_file.replace(".csv", "_variation_analysis.csv")
    #     self.variation_df.to_csv(variation_csv_file, index=False)
    #     print(f"Variation analysis CSV generated: {variation_csv_file}")

    #     # Generate time analysis CSV
    #     time_analysis_data = self.generate_time_analysis()
    #     time_df = pd.DataFrame([time_analysis_data])
    #     time_csv_file = output_file.replace(".csv", "_time_analysis.csv")
    #     time_df.to_csv(time_csv_file, index=False)
    #     print(f"Time analysis CSV generated: {time_csv_file}")

    #     # Generate traffic type analysis CSV
    #     traffic_analysis_data = self.generate_traffic_type_analysis()
    #     traffic_df = pd.DataFrame([traffic_analysis_data])
    #     traffic_csv_file = output_file.replace(".csv", "_traffic_analysis.csv")
    #     traffic_df.to_csv(traffic_csv_file, index=False)
    #     print(f"Traffic analysis CSV generated: {traffic_csv_file}")

    def generate_comparison_report(
        self,
        html_output="traffic_comparison_report.html",
        csv_output="traffic_comparison_report.csv",
    ):
        """Generate both HTML and CSV reports"""
        print("Starting traffic analysis comparison...")

        # Compare locations
        comparison_df = self.compare_locations()

        if comparison_df.empty:
            print("No matching locations found for comparison.")
            return

        print(f"Compared {len(comparison_df)} locations")
        print(f"Typical traffic locations: {len(self.typical_comparison_df)}")
        print(f"Live traffic locations: {len(self.live_comparison_df)}")

        # Generate reports
        self.generate_html_report(html_output)
        # self.generate_csv_report(csv_output)

        # Print quick summary to console
        summary = self.generate_summary_stats()
        print(f"\n=== COMPREHENSIVE COMPARISON SUMMARY ===")
        print(f"Locations compared: {summary['total_locations_compared']}")
        print(f"Average Selenium score: {summary['avg_score_selenium']:.2f}")
        print(f"Average Playwright score: {summary['avg_score_playwright']:.2f}")
        print(
            f"Average score difference: {summary['avg_score_improvement']:.2f} points ({summary['avg_score_improvement_pct']:.1f}%)"
        )
        print(
            f"Processing time - Selenium: {summary['selenium_total_processing_time']:.1f}s, Playwright: {summary['playwright_total_processing_time']:.1f}s"
        )
        print(
            f"Processing time difference: {summary['processing_time_difference']:.1f}s ({summary['processing_time_difference_pct']:.1f}%)"
        )
        print(f"Traffic type consistency: {summary['traffic_type_consistency']:.1f}%")
        print(f"Locations with higher scores: {summary['locations_with_improvement']}")
        print(
            f"Storefront detection difference: {summary['storefront_detection_improvement']}"
        )
        print(
            f"Average score variation: {summary['mean_relative_difference_score']:.1f}%"
        )
        print(f"Overall consistency: {summary['consistency_score_based']:.1f}%")


def main():
    # File paths - update these to match your actual file locations
    selenium_file = "selenium_combined.json"
    playwright_file = "playwright_combined.json"

    # Initialize comparator
    comparator = TrafficAnalysisComparator(selenium_file, playwright_file)

    # Generate a comprehensive reports
    comparator.generate_comparison_report(
        html_output="traffic_analysis_comparison_report.html",
        csv_output="traffic_analysis_comparison_report.csv",
    )


if __name__ == "__main__":
    main()
