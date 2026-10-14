<?php

use Illuminate\Database\Migrations\Migration;
use Illuminate\Database\Schema\Blueprint;
use Illuminate\Support\Facades\Schema;

return new class extends Migration {
    public function up(): void
    {
        Schema::create('posts', function (Blueprint $table) {
            $table->ulid('id')->primary();
            $table->foreignId('author_id')->constrained('users');
            $table->string('title');
            $table->string('slug')->unique();
            $table->text('body');
            $table->enum('state', ['draft', 'published'])->default('draft');
            $table->unsignedTinyInteger('rating')->nullable();
            $table->timestamp('published_at')->nullable()->useCurrent();
            $table->timestamps();
        });
    }
};
