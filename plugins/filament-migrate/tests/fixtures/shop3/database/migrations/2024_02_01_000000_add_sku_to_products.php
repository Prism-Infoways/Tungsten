<?php

use Illuminate\Database\Migrations\Migration;
use Illuminate\Database\Schema\Blueprint;
use Illuminate\Support\Facades\Schema;

return new class extends Migration
{
    public function up(): void
    {
        Schema::table('products', function (Blueprint $table) {
            $table->string('sku', 64)->nullable()->after('slug');
            $table->renameColumn('stock', 'quantity');
        });

        Schema::table('customers', function (Blueprint $table) {
            $table->dropColumn(['gender']);
        });

        Schema::dropIfExists('temp_imports');
    }

    public function down(): void
    {
        Schema::table('products', function (Blueprint $table) {
            $table->dropColumn('sku');
        });
    }
};
